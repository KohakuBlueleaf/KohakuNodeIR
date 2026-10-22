"""K1 user tooling: linked execution, authored round trips, and source queries."""

import importlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kohakunode.cli.main import main
from kohakunode.compiler import compile_file
from kohakunode.lsp.analysis import (
    analyze,
    completions,
    definition_location,
    format_text,
    hover,
    signature_help,
)
from kohakunode.syntax import parse, write

LIB = """@export identity
@def (x: int = 7)identity(y: int):
    y = x
@def ()private(y: int):
    y = 99
"""
SOURCE = '@import "lib.kir" as lib\n(3)lib.identity(result)\n'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def entry(tmp_path):
    (tmp_path / "lib.kir").write_text(LIB, encoding="utf-8")
    path = tmp_path / "main.kir"
    path.write_text(SOURCE, encoding="utf-8")
    return path


def test_cli_linked_check_run_lower_hash(entry, capsys):
    assert main(["check", str(entry)]) == 0
    assert not capsys.readouterr().err
    assert main(["run", str(entry)]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == 3
    assert main(["lower", str(entry), "--passes", ""]) == 0
    lowered = capsys.readouterr().out
    assert "@import" not in lowered and "_kir_" in lowered
    parse(lowered)
    assert main(["lower", str(entry), "--hash"]) == 0
    hashes = capsys.readouterr().out
    assert compile_file(entry).semantic_hash in hashes
    entry.with_name("lib.kir").write_text(LIB.replace("99", "98"), encoding="utf-8")
    assert main(["lower", str(entry), "--hash"]) == 0
    assert capsys.readouterr().out != hashes


def test_cli_authoring_preserves_declarations_without_resolving(entry, tmp_path, capsys):
    source = '@import "lib.kir" as lib\n@export public\n@def ()public(y: int):\n    y = 1\n(3)lib.identity(result)\n'
    entry.write_text(source, encoding="utf-8")
    entry.with_name("lib.kir").unlink()
    assert main(["fmt", str(entry)]) == 0
    assert capsys.readouterr().out == write(parse(source))
    graph_path = tmp_path / "main.kirgraph"
    assert main(["graph", str(entry), "-o", str(graph_path)]) == 0
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph["imports"] == [{"module": "lib.kir", "alias": "lib"}]
    assert graph["exports"] == ["public"]
    assert main(["text", str(graph_path), "--no-meta"]) == 0
    assert parse(capsys.readouterr().out) == parse(source)


def test_cli_errors_name_imported_source(entry, capsys):
    entry.with_name("lib.kir").write_text(LIB.replace("y = x", "y = missing"), encoding="utf-8")
    assert main(["check", str(entry)]) == 1
    assert "lib.kir" in capsys.readouterr().out
    entry.write_text('@import "lib.kir"\n', encoding="utf-8")
    assert main(["check", str(entry)]) == 1
    assert str(entry) in capsys.readouterr().out
    assert main(["run", str(entry.with_name("missing.kir"))]) == 1
    assert "missing.kir" in capsys.readouterr().err


@pytest.mark.parametrize("passes", [[], ["--passes", ""]])
def test_cli_runtime_origin_for_nested_imports(tmp_path, capsys, passes):
    (tmp_path / "inner.kir").write_text(
        "@export fail\n@def (x: int)fail(y: float):\n    (x, 0)div(y)\n",
        encoding="utf-8",
    )
    (tmp_path / "wrapper.kir").write_text(
        '@import "inner.kir" as inner\n@export outer\n@def (x: int)outer(y: float):\n    (x)inner.fail(y)\n',
        encoding="utf-8",
    )
    entry = tmp_path / "main.kir"
    entry.write_text(
        '@import "wrapper.kir" as wrapper\n(1)wrapper.outer(result)\n', encoding="utf-8"
    )
    assert main(["run", str(entry), *passes]) == 1
    error = capsys.readouterr().err
    assert "ZeroDivisionError: division by zero" in error
    assert "source: inner.kir:3 (@def fail)" in error
    assert "call chain: main.kir:2 -> wrapper.kir:4 (@def outer)" in error

    entry.write_text(
        '@import "wrapper.kir" as wrapper\n@try:\n    (1)wrapper.outer(result)\n@except err:\n    caught = err\n',
        encoding="utf-8",
    )
    assert main(["run", str(entry), *passes]) == 0
    output = capsys.readouterr()
    assert not output.err
    caught = json.loads(output.out)["caught"]
    assert caught["message"] == "division by zero"
    assert set(caught) == {"kind", "node", "message"}


@pytest.mark.parametrize("core", ["python", "rust"])
def test_lsp_exported_queries_and_formatter(entry, core):
    if core == "rust":
        pytest.importorskip("kohakunode._rs")
    a = analyze(SOURCE, str(entry), core=core)
    assert not a.problems
    items = completions(a, SOURCE, 1, 8)
    assert ("lib.identity", "def") in items
    assert ("lib.private", "def") not in items
    description = hover(a, SOURCE, 1, 9)
    assert "x: int = 7" in description and "lib.identity" in description
    assert "lib.kir" in description
    target = definition_location(a, SOURCE, 1, 9)
    assert Path(target.path) == entry.with_name("lib.kir") and target.line == 1
    assert "lib.identity" in signature_help(a, SOURCE, 1, len("(3)lib.identity("))
    assert format_text(SOURCE, core) == write(parse(SOURCE))
    assert ("import", "directive") in completions(a, "@", 0, 1)
    assert ("export", "directive") in completions(a, "@", 0, 1)


def test_lsp_native_dispatch_and_formatting(entry, monkeypatch):
    analysis = importlib.import_module("kohakunode.lsp.analysis")
    calls = []

    def compile_native(text, modules, source_name, **kwargs):
        calls.append((text, modules, source_name, kwargs))
        return json.dumps(
            {
                "diagnostics": [
                    {
                        "code": "W999",
                        "severity": "warning",
                        "message": "native diagnostic",
                        "line": 2,
                    }
                ]
            }
        )

    def no_python_compile(*args, **kwargs):
        raise AssertionError("Rust-selected diagnostics must not use the Python compiler")

    class NativeError(Exception):
        pass

    native = SimpleNamespace(
        compile_modules=compile_native,
        format=lambda text: "native formatting\n",
        KirError=NativeError,
        KirSyntaxError=NativeError,
        KirCheckError=NativeError,
        KirSignatureError=NativeError,
    )
    monkeypatch.setattr(analysis, "_rs", native)
    monkeypatch.setattr(analysis, "compile_program", no_python_compile)
    a = analyze(SOURCE, str(entry), core="rust", modules={"lib.kir": LIB})
    assert a.problems[0].message == "native diagnostic"
    assert ("lib.identity", "def") in completions(a, SOURCE, 1, 9)
    assert calls[0][2] == "main.kir"
    assert json.loads(calls[0][1]) == {"lib.kir": LIB}
    assert calls[0][3] == {"passes": [], "base": str(entry.parent), "sig_path": []}
    analyze(SOURCE, str(entry), core="rust")
    assert calls[-1][1] is None
    assert format_text(SOURCE, "rust") == "native formatting\n"


def test_lsp_old_native_extension_fallback_is_explicit(entry, monkeypatch):
    analysis = importlib.import_module("kohakunode.lsp.analysis")
    monkeypatch.setattr(analysis, "_rs", SimpleNamespace())
    with pytest.warns(RuntimeWarning, match="lacks source-module support"):
        a = analyze(SOURCE, str(entry), core="rust")
    assert not a.problems
    with pytest.warns(RuntimeWarning, match="lacks source-module support"):
        assert format_text(SOURCE, "rust") == write(parse(SOURCE))


@pytest.mark.parametrize("case", ["valid", "private", "body_error", "missing", "cycle", "syntax"])
def test_lsp_native_diagnostics_match_reference(entry, monkeypatch, case):
    analysis = importlib.import_module("kohakunode.lsp.analysis")
    if analysis._rs is None or not hasattr(analysis._rs, "compile_modules"):
        pytest.skip("requires a source-module-capable Rust extension")
    text, modules = SOURCE, {"lib.kir": LIB}
    if case == "private":
        text = text.replace("lib.identity", "lib.private")
    elif case == "body_error":
        modules["lib.kir"] = LIB.replace("y = x", "unused = 1\n    y = missing")
    elif case == "missing":
        modules = {}
    elif case == "cycle":
        modules["lib.kir"] = '@import "main.kir" as main\n' + LIB
    elif case == "syntax":
        text = '@import "lib.kir"\n'
    expected = analyze(text, str(entry), core="python", modules=modules)

    def no_python_compile(*args, **kwargs):
        raise AssertionError("native diagnostics invoked the Python compiler")

    monkeypatch.setattr(analysis, "compile_program", no_python_compile)
    actual = analyze(text, str(entry), core="rust", modules=modules)
    if case == "syntax":
        # Invalid preambles can produce different recovery columns in the two
        # grammars. The selected native parser, not Python, owns this location.
        with pytest.raises(analysis._rs.KirSyntaxError) as native_error:
            analysis._rs.compile_modules(text, json.dumps(modules), entry.name, passes=[])
        assert [(p.code, p.line) for p in actual.problems] == [
            (p.code, p.line) for p in expected.problems
        ]
        assert actual.problems[0].message == str(native_error.value)
        where = re.search(r"column (\d+)\)$", str(native_error.value))
        assert actual.problems[0].start == int(where[1]) - 1
    else:
        assert actual.problems == expected.problems
    if case == "body_error":
        assert {p.code for p in actual.problems} >= {"E020", "W020"}


@pytest.mark.parametrize("core", ["python", "rust"])
def test_lsp_incomplete_call_retains_imported_completions(entry, core):
    text = '@import "lib.kir" as lib\n(3)lib.'
    if core == "rust":
        pytest.importorskip("kohakunode._rs")
    a = analyze(text, str(entry), core=core)
    assert a.problems[0].code == "E001"
    assert ("lib.identity", "def") in completions(a, text, 1, 7)


def test_lsp_link_errors_and_source_anchoring(entry):
    bad = SOURCE.replace("lib.identity", "lib.private")
    a = analyze(bad, str(entry), core="python")
    assert any("not exported" in p.message for p in a.problems)
    entry.with_name("lib.kir").write_text(LIB.replace("y = x", "y = missing"), encoding="utf-8")
    a = analyze(SOURCE, str(entry), core="python")
    problem = next(p for p in a.problems if p.code == "E020")
    assert problem.line == 0 and "lib.kir" in problem.message and "source line 3" in problem.message
    entry.with_name("lib.kir").unlink()
    assert any("lib.kir" in p.message for p in analyze(SOURCE, str(entry), core="python").problems)


@pytest.mark.parametrize("core", ["python", "rust"])
def test_lsp_module_map_authoritative_and_no_implementation_import(entry, monkeypatch, core):
    if core == "rust":
        pytest.importorskip("kohakunode._rs")
    monkeypatch.syspath_prepend(str(entry.parent))
    heavy_name = "k1_tools_heavy"
    entry.with_name(heavy_name + ".py").write_text(
        "raise AssertionError('must not import')\n", encoding="utf-8"
    )
    signature = {
        "kirsig": 1,
        "library": heavy_name,
        "nodes": [
            {
                "name": "echo",
                "inputs": [{"name": "x", "type": "int"}],
                "outputs": [{"name": "y", "type": "int"}],
            }
        ],
    }
    entry.with_name(heavy_name + ".kirsig.json").write_text(json.dumps(signature), encoding="utf-8")
    library = f'@use "{heavy_name}" as h\n' + LIB.replace("y = x", "(x)h.echo(y)")
    a = analyze(
        SOURCE,
        str(entry),
        sig_path=[str(entry.parent)],
        core=core,
        modules={"lib.kir": library},
    )
    assert not a.problems and heavy_name not in sys.modules
    assert "lib.identity" in hover(a, SOURCE, 1, 9)
    missing = analyze(SOURCE, str(entry), core=core, modules={})
    assert "module map" in missing.problems[0].message
    assert ("lib.identity", "def") not in completions(missing, SOURCE, 1, 8)


def test_lsp_protocol_cross_file_definition_and_signature(entry, monkeypatch):
    pytest.importorskip("pygls")
    server = importlib.import_module("kohakunode.lsp.server")
    types = importlib.import_module("lsprotocol.types")
    uri = entry.as_uri()
    doc = SimpleNamespace(uri=uri, path=str(entry), source=SOURCE)
    fake = SimpleNamespace(workspace=SimpleNamespace(get_text_document=lambda _: doc))
    monkeypatch.setattr(server, "server", fake)
    monkeypatch.setitem(server.state, "analyses", {uri: analyze(SOURCE, str(entry), core="python")})
    params = types.DefinitionParams(
        text_document=types.TextDocumentIdentifier(uri), position=types.Position(1, 9)
    )
    location = server.on_definition(params)
    assert location.uri == entry.with_name("lib.kir").as_uri()
    assert location.range.start.line == 1
    signatures = server.on_signature_help(params)
    assert "lib.identity" in signatures.signatures[0].label
    completed = server.on_completion(params)
    item = next(i for i in completed.items if i.label == "lib.identity")
    assert item.text_edit.range.start.character == 3
    assert item.text_edit.new_text == "lib.identity"


def test_lsp_save_refreshes_importers(entry, monkeypatch):
    pytest.importorskip("pygls")
    server = importlib.import_module("kohakunode.lsp.server")
    types = importlib.import_module("lsprotocol.types")
    uri = entry.as_uri()
    library = entry.with_name("lib.kir")
    lib_uri = library.as_uri()
    docs = {
        uri: SimpleNamespace(uri=uri, path=str(entry), source=SOURCE),
        lib_uri: SimpleNamespace(uri=lib_uri, path=str(library), source=LIB),
    }
    published = []
    fake = SimpleNamespace(
        workspace=SimpleNamespace(get_text_document=docs.__getitem__),
        text_document_publish_diagnostics=published.append,
    )
    monkeypatch.setattr(server, "server", fake)
    monkeypatch.setitem(server.state, "core", "python")
    monkeypatch.setitem(server.state, "analyses", {})
    server.refresh(uri)
    changed = LIB.replace("identity", "renamed")
    library.write_text(changed, encoding="utf-8")
    docs[lib_uri].source = changed
    server.did_save(types.DidSaveTextDocumentParams(types.TextDocumentIdentifier(lib_uri)))
    refreshed = server.state["analyses"][uri]
    assert ("lib.renamed", "def") in completions(refreshed, SOURCE, 1, 9)
    assert ("lib.identity", "def") not in completions(refreshed, SOURCE, 1, 9)
    assert any("not exported" in p.message for p in refreshed.problems)
    assert published[-1].uri == uri and published[-1].diagnostics
    server.did_close(types.DidCloseTextDocumentParams(types.TextDocumentIdentifier(uri)))
    assert uri not in server.state["analyses"]


def test_editor_ast_and_api_module_maps(monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.syspath_prepend(str(ROOT / "apps/kir-editor/backend"))
    ast_json = importlib.import_module("kir_editor.core.ast_json")
    toolchain = importlib.import_module("kir_editor.core.toolchain")
    schemas = importlib.import_module("kir_editor.api.schemas")
    config = importlib.import_module("kir_editor.config")
    source = "@export identity\n" + LIB.split("\n", 1)[1]
    ast = ast_json.program_to_json(parse(source))
    assert ast_json.program_from_json(ast) == parse(source)
    request = schemas.SourceRequest(
        text=SOURCE, modules={"lib.kir": LIB}, source_name="main.kir", use_demo=False
    )
    tools = toolchain.Toolchain(config.Settings())
    scope = request.scope()
    assert not tools.check(SOURCE, scope)["diagnostics"]
    graph = tools.graph(SOURCE, scope)
    assert not graph["diagnostics"]
    assert graph["ast"]["imports"] == [{"module": "lib.kir", "alias": "lib"}]
    assert parse(tools.ast_text(graph["ast"], scope)["text"]) == parse(SOURCE)
    assert tools.run(SOURCE, scope)["values"]["result"] == 3
    assert "@import" not in tools.lower(SOURCE, scope)["lowered"]
    for bad in (
        {"imports": [{"module": "lib.kir"}]},
        {"imports": [None]},
        {"imports": "lib.kir"},
        {"exports": "identity"},
    ):
        result = tools.ast_text(bad, scope)
        assert result["text"] is None and result["diagnostics"]


def test_vscode_module_tokens():
    grammar = json.loads(
        (ROOT / "editors/vscode/syntaxes/kir.tmLanguage.json").read_text(encoding="utf-8")
    )
    imports = grammar["repository"]["import"]
    assert re.fullmatch(imports["match"], '@import "lib.kir" as lib')
    assert not re.fullmatch(imports["match"], '@import "lib.kir"')
    assert re.fullmatch(grammar["repository"]["export"]["match"], "@export identity")


def test_frontend_statement_roundtrip_preserves_modules():
    if shutil.which("node") is None:
        pytest.skip("Node.js is needed for the frontend projection test")
    script = """
import {programTree, treeToAst} from './apps/kir-editor/frontend/src/program/structure.js';
const ast = {uses: [], imports: [{module: 'lib.kir', alias: 'lib'}], exports: ['public'], mode: null, body: []};
const result = treeToAst(programTree(ast));
if (JSON.stringify(result) !== JSON.stringify(ast)) throw new Error(JSON.stringify(result));
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT, check=True, capture_output=True
    )
