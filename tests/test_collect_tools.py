"""K4 collection controls across CLI, LSP and editor projections."""

import importlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from kohakunode.cli.main import build_parser, main
from kohakunode.lsp.analysis import analyze, completions, format_text, hover, signature_help
from kohakunode.syntax import parse, write
from kohakunode.syntax.ast import Collect

ROOT = Path(__file__).resolve().parents[1]
SOURCE = """xs = [1, 2]
(xs)collect(item, i, `body`, value -> results)
body:
    (item, 1)add(value)
"""


def test_lsp_collect_builtin_queries():
    a = analyze(SOURCE, core="python")
    assert not [p for p in a.problems if p.severity == "error"]
    assert ("collect", "builtin") in completions(a, SOURCE, 1, 7)
    doc = hover(a, SOURCE, 1, 8)
    assert "value -> results" in doc and "normal body end" in doc
    assert "only after all iterations complete" in doc
    assert "deferred (`body_end`)" in doc and "not an ordinary runtime node call" in doc
    assert "h.collect" in doc
    assert signature_help(a, SOURCE, 1, len("(xs)collect(")) == doc
    assert format_text(SOURCE, "python") == write(parse(SOURCE))
    partial = "(xs)collect("
    assert "value -> results" in signature_help(
        analyze(partial, core="python"), partial, 0, len(partial)
    )


def test_collect_old_native_fallback_warns(monkeypatch):
    analysis = importlib.import_module("kohakunode.lsp.analysis")
    old = ModuleType("old_native")

    class NativeError(Exception):
        pass

    def no_syntax(_):
        raise NativeError("collect syntax unavailable")

    old.KirError = NativeError
    old.parse_to_json = no_syntax
    monkeypatch.setattr(analysis, "_rs", old)
    with pytest.warns(RuntimeWarning, match="lacks collect syntax support"):
        actual = analyze(SOURCE, core="rust")
    assert not actual.problems
    with pytest.warns(RuntimeWarning, match="lacks collect syntax support"):
        assert format_text(SOURCE, "rust") == write(parse(SOURCE))


def test_collect_native_when_available(monkeypatch):
    analysis = importlib.import_module("kohakunode.lsp.analysis")
    native = pytest.importorskip("kohakunode._rs")
    if not analysis._native_collect_supported(native):
        pytest.skip("installed native extension predates collect syntax")
    expected = analyze(SOURCE, core="python").problems

    def no_python(*args, **kwargs):
        raise AssertionError("native-selected collect must stay native")

    monkeypatch.setattr(analysis, "check", no_python)
    monkeypatch.setattr(analysis, "compile_program", no_python)
    monkeypatch.setattr(analysis, "write", no_python)
    assert analyze(SOURCE, core="rust").problems == expected
    assert format_text(SOURCE, "rust") == native.format(SOURCE)


@pytest.mark.parametrize("passes", [[], ["--passes", ""]])
def test_cli_collect_check_run_lower(tmp_path, capsys, passes):
    path = tmp_path / "collect.kir"
    path.write_text(SOURCE, encoding="utf-8")
    assert main(["check", str(path)]) == 0
    capsys.readouterr()
    assert main(["run", str(path), *passes]) == 0
    assert json.loads(capsys.readouterr().out)["results"] == [2, 3]
    assert main(["lower", str(path)]) == 0
    assert ")collect(" not in capsys.readouterr().out
    assert (
        "expand_collect"
        in build_parser()._subparsers._group_actions[0].choices["lower"].format_help()
    )


@pytest.mark.parametrize(
    "header",
    [
        "(xs)collect(item, `body`, value -> results)",
        "(xs)collect(_, _, `body`, None -> results)",
    ],
)
def test_editor_collect_ast_roundtrip(monkeypatch, header):
    monkeypatch.syspath_prepend(str(ROOT / "apps/kir-editor/backend"))
    ast_json = importlib.import_module("kir_editor.core.ast_json")
    text = f"xs = [1]\n{header}\nbody:\n    value = 3\n"
    p = parse(text)
    data = ast_json.program_to_json(p)
    control = data["body"][1]
    assert control["type"] == "collect"
    assert set(control) >= {"items", "item", "index", "label", "value", "target", "has_index"}
    assert ast_json.program_from_json(data) == p
    assert write(ast_json.program_from_json(data)) == write(p)
    assert isinstance(p.body[1], Collect)


def test_editor_collect_graph_and_pass_catalog(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "apps/kir-editor/backend"))
    toolchain = importlib.import_module("kir_editor.core.toolchain")
    config = importlib.import_module("kir_editor.config")
    tools = toolchain.Toolchain(config.Settings())
    scope = toolchain.Scope(use_demo=False)
    assert "expand_collect" in {p["name"] for p in tools.passes()}
    for style in ("wires", "variables"):
        result = tools.graph(SOURCE, scope, style)
        assert not result["diagnostics"]
        node = next(n for n in result["graph"]["graphs"][0]["nodes"] if n["kind"] == "collect")
        assert next(p for p in node["inputs"] if p["port"] == "value")["deferred"] == "body_end"
        text = tools.text(result["graph"], scope, with_meta=False)
        assert not text["diagnostics"]
        assert tools.run(text["text"], scope)["values"]["results"] == [2, 3]
    assert tools.run(SOURCE, scope, passes=[])["values"]["results"] == [2, 3]


def test_collect_statement_projection_and_graph_factory(monkeypatch):
    if shutil.which("node") is None:
        pytest.skip("Node.js required for frontend projections")
    monkeypatch.syspath_prepend(str(ROOT / "apps/kir-editor/backend"))
    ast_json = importlib.import_module("kir_editor.core.ast_json")
    data = ast_json.program_to_json(parse(SOURCE))
    # Resolve @/ imports through a tiny Node loader, without starting a browser.
    script = """
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
registerHooks({resolve(specifier, context, next) {
  if (specifier.startsWith('@/')) return {url: pathToFileURL(resolve('apps/kir-editor/frontend/src', specifier.slice(2) + '.js')).href, shortCircuit: true};
  return next(specifier, context);
}});
const {programTree, treeToAst, variables} = await import('./apps/kir-editor/frontend/src/program/structure.js');
const {itemFor} = await import('./apps/kir-editor/frontend/src/program/create.js');
const {makeNode, serializeGraph, isValidConnection, connect} = await import('./apps/kir-editor/frontend/src/graph/edit.js');
const {isBackEdge} = await import('./apps/kir-editor/frontend/src/graph/ports.js');
const ast = JSON.parse(process.argv[1]);
const tree = programTree(ast);
if (tree.body[1].t !== 'group' || tree.body[1].arms.length !== 1) throw new Error('collect body not grouped');
if (JSON.stringify(treeToAst(tree)) !== JSON.stringify(ast)) throw new Error('roundtrip changed AST');
if (!variables(tree).includes('results')) throw new Error('result list missing');
const created = itemFor({kind: 'collect'}, tree);
if (created.s.target === 'results' || created.s.value.name !== created.s.item) throw new Error('fresh collect names/capture incorrect');
const graph = {nodes: [], edges: []};
const node = makeNode(graph, {kind: 'collect'}); graph.nodes.push(node);
if (node.inputs.find(p => p.port === 'value').deferred !== 'body_end') throw new Error('lost deferred capture');
if (serializeGraph(graph).nodes[0].inputs[1].deferred !== 'body_end') throw new Error('serialize lost capture timing');
if (!isBackEdge({kind: 'ctrl', to: {node: node.id, port: 'next'}}, new Map([[node.id,node]]))) throw new Error('return edge not loop');
const capture = {source: node.id, target: node.id, sourceHandle: 'data:out:item', targetHandle: 'data:in:value'};
if (!isValidConnection(capture, graph) || !connect(graph, capture)) throw new Error('valid self capture rejected');
if (!isValidConnection({...capture, sourceHandle: 'data:out:index'}, graph)) throw new Error('index capture rejected');
if (isValidConnection({...capture, sourceHandle: 'data:out:results'}, graph)) throw new Error('unfinished results self capture accepted');
if (isValidConnection({...capture, targetHandle: 'data:in:items'}, graph)) throw new Error('eager self dependency accepted');
console.log(JSON.stringify(graph));
"""
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(data)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    graph = json.loads(out.stdout)
    from_graph = importlib.import_module("kohakunode.graph").from_graph
    restored = from_graph(
        {"kirgraph": 2, "uses": [], "graphs": [{"name": "main", **graph}]}, with_meta=False
    )
    assert isinstance(restored.body[0], Collect)
    assert restored.body[0].value.id == restored.body[0].item


def test_collect_highlight_and_snippets():
    grammar = json.loads(
        (ROOT / "editors/vscode/syntaxes/kir.tmLanguage.json").read_text(encoding="utf-8")
    )
    assert re.search(grammar["repository"]["builtin-outputs"]["begin"], "(xs)collect(")
    assert re.fullmatch(grammar["repository"]["output-items"]["patterns"][1]["match"], "->")
    snippets = json.loads(
        (ROOT / "editors/vscode/snippets/kir.code-snippets").read_text(encoding="utf-8")
    )
    assert snippets["Collect"]["prefix"] == "collect"
    assert "->" in snippets["Collect with index"]["body"][0]


def test_lsp_collect_signature_protocol(monkeypatch):
    pytest.importorskip("pygls")
    server = importlib.import_module("kohakunode.lsp.server")
    types = importlib.import_module("lsprotocol.types")
    uri = "file:///collect.kir"
    doc = SimpleNamespace(uri=uri, source=SOURCE)
    monkeypatch.setattr(
        server,
        "server",
        SimpleNamespace(workspace=SimpleNamespace(get_text_document=lambda _: doc)),
    )
    monkeypatch.setitem(server.state, "analyses", {uri: analyze(SOURCE, core="python")})
    result = server.on_signature_help(
        types.SignatureHelpParams(
            text_document=types.TextDocumentIdentifier(uri), position=types.Position(1, 12)
        )
    )
    assert "value -> results" in result.signatures[0].label
