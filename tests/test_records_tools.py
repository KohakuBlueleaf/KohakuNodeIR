"""K3 schema tooling reads signature data, never host implementation modules."""

import copy
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kohakunode.cli.main import main
from kohakunode.lsp.analysis import analyze, completions, hover, signature_help
from kohakunode.sig.files import library_from_json, library_to_json
from kohakunode.syntax import parse, write

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = {
    "kirsig": 2,
    "library": "geometry",
    "nodes": [],
    "records": [
        {
            "name": "Point",
            "fields": [
                {"name": "x", "type": "int"},
                {"name": "y", "type": "int", "default": 0},
                {"name": "tags", "type": "list[str]", "default": []},
            ],
        }
    ],
}
SOURCE = """@use "geometry" as g
@def (point: g.Point)identity(out: geometry.Point):
    out = point
(1)g.Point.make(p)
p2: g.Point = p
(p2, 2)g.Point.with.x(q)
(q)g.Point.get.x(x)
(q)identity(result)
"""


@pytest.fixture
def schema_path(tmp_path, monkeypatch):
    (tmp_path / "geometry.kirsig.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    (tmp_path / "geometry.py").write_text(
        "raise AssertionError('host import forbidden')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path / "main.kir"


def analysis_for(text, path):
    return analyze(text, str(path), [str(path.parent)], "python")


@pytest.mark.parametrize("bad", [False, True])
def test_native_record_diagnostics_match_python_when_available(schema_path, monkeypatch, bad):
    analysis = importlib.import_module("kohakunode.lsp.analysis")
    native = pytest.importorskip("kohakunode._rs")
    try:
        native.check("", [json.dumps(SCHEMA)])
    except native.KirSignatureError as exc:
        if "unsupported signature format 2" in str(exc):
            pytest.skip("installed native extension predates record schema support")
        raise
    text = SOURCE.replace("(1)g.Point.make", '("wrong")g.Point.make') if bad else SOURCE
    expected = analysis_for(text, schema_path)

    def no_python_compiler(*args, **kwargs):
        raise AssertionError("Rust-selected schema diagnostics invoked Python compiler")

    monkeypatch.setattr(analysis, "compile_program", no_python_compiler)
    actual = analyze(text, str(schema_path), [str(schema_path.parent)], "rust")
    assert actual.problems == expected.problems
    assert "geometry.Point" in hover(actual, text, 4, 8)
    assert "geometry" not in sys.modules


def test_record_completions_hover_signatures_and_canonical_annotations(schema_path):
    a = analysis_for(SOURCE, schema_path)
    assert not a.problems
    assert "geometry" not in sys.modules
    items = completions(a, SOURCE, 3, 8)
    for name in ("g.Point.make", "g.Point.get.x", "g.Point.with.x"):
        assert (name, "node") in items
    assert ("g.Point", "type") in items and ("geometry.Point", "type") in items
    record = hover(a, SOURCE, 4, 8)
    assert "canonical `geometry.Point`" in record
    assert "`x: int`" in record and "`y: int` = `0`" in record
    assert "`tags: list[str]` = `[]`" in record
    assert "geometry.Point" in hover(
        a, SOURCE, 1, SOURCE.splitlines()[1].index("geometry.Point") + 1
    )
    constructor = signature_help(a, SOURCE, 3, len("(1)g.Point.make("))
    assert "x: int" in constructor and "y: int = 0" in constructor
    assert "record: geometry.Point" in constructor
    definition = hover(a, SOURCE, 7, 4)
    assert "point: geometry.Point" in definition and "out: geometry.Point" in definition
    assert a.program == parse(SOURCE)  # Canonical display/checking is not an authoring rewrite.


def test_record_completion_survives_incomplete_annotation(schema_path):
    text = '@use "geometry" as g\np: g.'
    a = analysis_for(text, schema_path)
    assert a.problems[0].code == "E001"
    assert ("g.Point", "type") in completions(a, text, 1, 5)


def test_record_ambiguity_does_not_crash_queries(schema_path):
    other = copy.deepcopy(SCHEMA)
    other["library"] = "other"
    schema_path.with_name("other.kirsig.json").write_text(json.dumps(other), encoding="utf-8")
    text = '@use "geometry"\n@use "other"\n@def (p: Point)f(q: Point):\n    q = p\n'
    a = analysis_for(text, schema_path)
    assert any(p.code == "E002" and "ambiguous record type" in p.message for p in a.problems)
    assert "ambiguous record type" in hover(a, text, 2, 10)
    names = completions(a, text, 2, 10)
    assert ("Point", "type") not in names
    assert ("geometry.Point", "type") in names and ("other.Point", "type") in names


def test_imported_schema_signature_uses_defining_alias(schema_path):
    library = '@use "geometry" as own\n@export identity\n@def (p: own.Point)identity(q: own.Point):\n    q = p\n'
    schema_path.with_name("lib.kir").write_text(library, encoding="utf-8")
    text = (
        '@use "geometry" as g\n@import "lib.kir" as lib\n(1)g.Point.make(p)\n(p)lib.identity(q)\n'
    )
    a = analysis_for(text, schema_path)
    assert not a.problems
    description = hover(a, text, 3, 8)
    assert "p: geometry.Point" in description and "q: geometry.Point" in description
    assert "own.Point" not in description and "lib.kir" in description


def test_cli_record_signature_file_run_check_and_authoring(schema_path, capsys):
    schema_path.write_text(SOURCE, encoding="utf-8")
    options = [str(schema_path), "--sig-path", str(schema_path.parent)]
    assert main(["check", *options]) == 0
    capsys.readouterr()
    assert main(["run", *options]) == 0
    assert json.loads(capsys.readouterr().out)["x"] == 2
    assert main(["fmt", str(schema_path)]) == 0
    assert capsys.readouterr().out == write(parse(SOURCE))
    assert "geometry" not in sys.modules


def test_editor_schema_v2_check_run_graph_and_catalog(schema_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.syspath_prepend(str(ROOT / "apps/kir-editor/backend"))
    toolchain = importlib.import_module("kir_editor.core.toolchain")
    config = importlib.import_module("kir_editor.config")
    tools = toolchain.Toolchain(config.Settings(sig_dirs=[schema_path.parent]))
    scope = toolchain.Scope(signatures=[SCHEMA], use_demo=False)
    assert not tools.check(SOURCE, scope)["diagnostics"]
    assert tools.run(SOURCE, scope)["values"]["x"] == 2
    graph = tools.graph(SOURCE, scope)
    assert not graph["diagnostics"]
    text = tools.text(graph["graph"], scope, with_meta=False)
    assert not text["diagnostics"] and "g.Point" in text["text"]
    catalog = next(lib for lib in tools.catalog() if lib.get("library") == "geometry")
    assert catalog["kirsig"] == 2 and catalog["records"] and catalog["runnable"]
    assert catalog["nodes"] == []  # Portable JSON derives operations rather than duplicating them.
    bad = copy.deepcopy(SCHEMA)
    bad["records"][0]["fields"][0]["type"] = "Missing"
    assert tools.check(SOURCE, toolchain.Scope(signatures=[bad], use_demo=False))["diagnostics"]


@pytest.mark.parametrize("nested", [False, True])
def test_frontend_record_palette_matches_core_without_mutating_signature(nested):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required for frontend projection tests")
    data = copy.deepcopy(SCHEMA)
    if nested:
        data["records"].append(
            {
                "name": "Box",
                "fields": [
                    {"name": "point", "type": "Point"},
                    {"name": "points", "type": "list[Point]"},
                    {"name": "named", "type": "dict[str, Point]"},
                    {"name": "payload", "type": " _ ", "default": None},
                    {"name": "dedup", "type": "int | int"},
                    {"name": "nil", "type": "None?", "default": None},
                    {"name": "formatted", "type": "list[ int | int ]"},
                ],
            }
        )
    library = library_from_json(data)
    # Ordinary signature serialization gives the authoritative expanded port metadata.
    model = importlib.import_module("kohakunode.sig.model")
    expected = library_to_json(model.Library(library.name, signatures=library.signatures))["nodes"]
    script = """
import {expandRecordSignatures, validateSignatureFile, projectLibraries} from './apps/kir-editor/frontend/src/program/signatures.js';
const raw = JSON.parse(process.argv[1]);
const before = JSON.stringify(raw);
validateSignatureFile(raw);
const projected = expandRecordSignatures(raw);
if (JSON.stringify(raw) !== before) throw new Error('raw upload mutated');
if (!projected.runnable) throw new Error('schema operations should be runnable');
const overlaid = projectLibraries([{...raw, records: [], source: 'disk'}], [raw]);
if (overlaid.length !== 1 || overlaid[0].source !== 'loaded file' || overlaid[0].nodes.length !== projected.nodes.length) throw new Error('upload did not replace stale catalog');
const legacy = {kirsig: 1, library: 'legacy', nodes: []};
validateSignatureFile(legacy);
if (expandRecordSignatures(legacy) !== legacy) throw new Error('legacy projection changed');
for (const invalid of [{...raw, kirsig: 1}, {...raw, records: null}, {...raw, records: [{name: 'Point', fields: [{name: 'x'}]}]}, {...raw, nodes: [{name: 'Point.make'}]}, {...raw, nodes: [{name: 'bad', inputs: [null]}]}, {...raw, nodes: [{name: 'bad', inputs: [{name: 'x', type: 123}]}]}]) {
  let rejected = false;
  try { validateSignatureFile(invalid); } catch { rejected = true; }
  if (!rejected) throw new Error('malformed schema accepted');
}
console.log(JSON.stringify(projected.nodes));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(data)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == expected
