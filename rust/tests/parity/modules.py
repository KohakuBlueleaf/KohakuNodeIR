"""Focused Python/native module + origin parity (optionally load a freshly built DLL).

python rust/tests/parity/modules.py --extension /absolute/path/to/kohakunode_rs.dll
"""
import argparse
import dataclasses
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
parser = argparse.ArgumentParser()
parser.add_argument("--extension")
args = parser.parse_args()
if args.extension:
    loader = importlib.machinery.ExtensionFileLoader("kohakunode._rs", str(Path(args.extension).resolve()))
    spec = importlib.util.spec_from_loader("kohakunode._rs", loader)
    native = importlib.util.module_from_spec(spec)
    loader.exec_module(native)
    sys.modules["kohakunode._rs"] = native

from kohakunode import _rs, compile_source, parse, write
from kohakunode.modules import link_program
from kohakunode.syntax.ast import walk
from kohakunode.sig.files import library_from_json


def origins(statements):
    result = []
    for stmt in statements:
        result.append(stmt.get("origin"))
        result.extend(origins(stmt.get("body", [])))
        result.extend(origins(stmt.get("handler", [])))
    return result


def py_origins(program):
    return json.loads(json.dumps([dataclasses.asdict(s.origin) if s.origin else None for s in walk(program.body)]))


CASES = [
    ("x = 1\n", {}),
    ('@import "id.kir" as lib\n()lib.id(x)\n(8)lib.id(y)\n', {
        "id.kir": "@export id\n@def (x: int = 7)id(y: int):\n    @meta node_id=original\n    y = x\n",
    }),
    ('@import "sub/a.kir" as a\n(3)a.f(y)\n', {
        "sub/a.kir": '@import "../b.kir" as b\n@export f\n@def (x)helper(y):\n    (x)b.f(y)\n@def (x)f(y):\n    (x)helper(y)\n',
        "b.kir": '@export f\n@def (x)helper(y):\n    (x, 1)add(y)\n@def (x)f(y):\n    (x)helper(y)\n',
    }),
    ('@import "lib.kir" as lib\n@def (a, b)add(c):\n    c = 999\n(3)lib.f(y)\n', {
        "lib.kir": '@export f\n@def (x)f(y):\n    (x, 1)add(y)\n',
    }),
    ('@import "lib.kir" as lib\n([1, 2], True)lib.f(y)\n', {
        "lib.kir": '@export f\n@def (xs: list, enabled: bool)f(result: list):\n    result = []\n    (xs)each(x, `body`)\n    body:\n        (enabled)branch(`yes`, `no`)\n        yes:\n            (result, x)append(result)\n        no:\n            skipped = x\n',
    }),
    ('@import "lib.kir" as lib\n@def (x: lib.Token)main(y: lib.Token):\n    (x)lib.id(y)\n', {
        "lib.kir": '@export id\n@def (x: Token)id(y: Token):\n    y = x\n',
    }),
    ('@import "a.kir" as a\n@def (x: a.b.Token)main(y: a.b.Token):\n    (x)a.id(y)\n', {
        "a.kir": '@import "b.kir" as b\n@export id\n@def (x: b.Token)id(y: b.Token):\n    (x)b.id(y)\n',
        "b.kir": '@export id\n@def (x: Token)id(y: Token):\n    y = x\n',
    }),
    ('@import "lib.kir" as lib\n(3)lib.f(y)\n', {
        "lib.kir": '@export f\n@typehint:\n    (int)host.call(int)\n@def (x: int)f(y: int):\n    (x)host.call(y)\n',
    }),
]

checks = 0
for index, (source, modules) in enumerate(CASES):
    expected_link = link_program(parse(source), modules=modules, source_name="main.kir")
    got_link = json.loads(_rs.link_modules(source, json.dumps(modules), "main.kir"))
    assert got_link["text"] == write(expected_link.program), (index, "linked text", got_link["text"], write(expected_link.program))
    assert got_link["dependencies"] == expected_link.dependencies, (index, "manifest", got_link["dependencies"], expected_link.dependencies)
    assert origins(got_link["program"]["body"]) == py_origins(expected_link.program), (index, "linked origins")
    for passes in [[], ["order_dataflow", "inline"], None]:
        expected = compile_source(source, modules=modules, source_name="main.kir", passes=passes)
        got = json.loads(_rs.compile_modules(source, json.dumps(modules), "main.kir", passes=passes))
        assert got["text"] == write(expected.program), (index, passes, "linked text")
        assert got["lowered_text"] == write(expected.lowered), (index, passes, "lowered text")
        assert got["dependencies"] == expected.dependencies, (index, passes, "manifest")
        assert got["semantic"] == expected.semantic_hash, (index, passes, "semantic", got["semantic"], expected.semantic_hash)
        assert got["full"] == expected.full_hash, (index, passes, "full")
        assert origins(got["lowered"]["body"]) == py_origins(expected.lowered), (index, passes, "lowered origins")
        diagnostics = [{"code": d.code, "message": d.message, "line": d.line, "severity": d.severity} for d in expected.diagnostics]
        assert got["diagnostics"] == diagnostics, (index, passes, "diagnostics", got["diagnostics"], diagnostics)
        checks += 1

# Contract canonicalization must agree on floats, signed zero, Unicode, nested
# defaults, and non-ASCII portable resource names, not merely integer defaults.
for default in [1e-7, 1e20, -0.0, "雪 café 😀", {"雪": [1e-7, -0.0, {"z": "😀", "a": 1e20}], "a": None}]:
    contract = {"kirsig": 1, "library": "host", "nodes": [
        {"name": "op", "inputs": [{"name": "x", "default": default}], "outputs": [{"name": "y"}], "doc": "ignored documentation"},
    ]}
    library = library_from_json(contract)
    source = '@import "資源/é.kir" as lib\n()lib.f(y)\n'
    modules = {"資源/é.kir": '@use "host" as h\n@export f\n@def ()f(y):\n    ()h.op(y)\n'}
    expected = compile_source(source, libraries=[library], modules=modules, source_name="入口.kir")
    got = json.loads(_rs.compile_modules(source, json.dumps(modules), "入口.kir", sigs=[json.dumps(contract)]))
    assert got["dependencies"] == expected.dependencies, ("contract manifest", default, got["dependencies"], expected.dependencies)
    assert got["semantic"] == expected.semantic_hash, ("contract hash", default)
    assert got["full"] == expected.full_hash, ("contract full hash", default)
    assert got["lowered_text"] == write(expected.lowered), ("contract lowering", default)
    checks += 1

for source, modules in [
    ('@import "absent.kir" as a\n', {}),
    ('@import "lib.kir" as a\n()a.private()\n', {"lib.kir": "@def ()private():\n    x = 1\n"}),
    ('@import "lib.kir" as a\n', {"lib.kir": "x = 1\n"}),
    ('@import "lib.kir" as a\n', {"lib.kir": '@import "main.kir" as main\n'}),
    ('@import "lib.kir" as _kir_alias\n', {"lib.kir": ""}),
    ('@export nonexistent\n', {}),
]:
    try:
        link_program(parse(source), modules=modules, source_name="main.kir")
    except Exception as exc:
        expected = str(exc)
    else:
        raise AssertionError("Python unexpectedly accepted invalid module")
    try:
        _rs.link_modules(source, json.dumps(modules), "main.kir")
    except Exception as exc:
        assert str(exc) == expected, (source, str(exc), expected)
    else:
        raise AssertionError("Rust unexpectedly accepted invalid module")
    checks += 1
for source, modules in [
    ('@import "lib.kir" as a\n(1)a.f(y)\n', {"lib.kir": '@export f\n@def (x)f(y):\n    (x)f(y)\n'}),
    ('@import "lib.kir" as a\n("bad")a.f(y)\n', {"lib.kir": '@export f\n@def (x: int)f(y: int):\n    y = x\n'}),
    ('@import "lib.kir" as a\n', {"lib.kir": '@export f\n@def ()f(y):\n    @dataflow:\n        (x)identity(y)\n        (y)identity(x)\n'}),
    ('@import "lib.kir" as a\n_kir_capture = 1\n', {"lib.kir": ''}),
    ('@import "lib.kir" as a\nx: _kir_Fake = 1\n', {"lib.kir": ''}),
]:
    try:
        compile_source(source, modules=modules, source_name="main.kir")
    except Exception as exc:
        expected = str(exc)
        expected_diagnostics = [{"code": d.code, "message": d.message, "line": d.line, "severity": d.severity} for d in exc.diagnostics]
    else:
        raise AssertionError("Python unexpectedly accepted invalid compilation")
    try:
        _rs.compile_modules(source, json.dumps(modules), "main.kir")
    except Exception as exc:
        assert str(exc) == expected, (source, str(exc), expected)
        assert json.loads(exc.diagnostics) == expected_diagnostics
    else:
        raise AssertionError("Rust unexpectedly accepted invalid compilation")
    checks += 1
depth = 24
source = "".join(
    f"@def ()f{i}():\n    ()f{i + 1}()\n" if i + 1 < depth else f"@def ()f{i}():\n    x = 1\n"
    for i in range(depth)
) + "()f0()\n"
expected = compile_source(source, source_name="deep.kir", passes=["order_dataflow", "inline"])
got = json.loads(_rs.compile_modules(source, "{}", "deep.kir", passes=["order_dataflow", "inline"]))
assert origins(got["lowered"]["body"]) == py_origins(expected.lowered), "deep shallow-ancestry parity"
leaf = got["lowered"]["body"][0]["origin"]
assert len(leaf["calls"]) == depth
assert all(not call["calls"] for call in leaf["calls"])
assert len(json.dumps(leaf)) < 10000, "ancestry grows beyond a flat callsite sequence"
checks += 1
import tempfile
with tempfile.TemporaryDirectory(dir=REPO / "rust" / "target") as directory:
    root = Path(directory)
    source = '@import "lib.kir" as lib\n()lib.id(result)\n'
    (root / 'lib.kir').write_text('@export id\n@def (x=7)id(y):\n    y = x\n', encoding='utf-8')
    expected = compile_source(source, base_dir=root, source_name='main.kir')
    got = json.loads(_rs.compile_modules(source, None, 'main.kir', base=root, sig_path=[]))
    assert got['semantic'] == expected.semantic_hash
    assert got['dependencies'] == expected.dependencies
    assert got['lowered_text'] == write(expected.lowered)
    try:
        _rs.compile_modules(source, '{}', 'main.kir', base=root)
    except _rs.KirCheckError as exc:
        assert json.loads(exc.diagnostics)[0]['code'] == 'E002'
    else:
        raise AssertionError('authoritative empty map unexpectedly fell back to files')
checks += 1
print(f"Module/origin parity: {checks} compilation/error cases passed")
