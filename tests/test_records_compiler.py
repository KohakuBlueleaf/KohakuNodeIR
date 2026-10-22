"""Record schemas remain nominal across annotations, modules and dependencies."""

import pytest

from kohakunode import (
    Interpreter,
    KirCheckError,
    KirSignatureError,
    NodeLibrary,
    build_env,
    check,
    compile_source,
    parse,
)
from kohakunode.modules import contract_hash
from kohakunode.sig.files import save_library
from kohakunode.sig.types import parse_type


def geometry(default=0):
    library = NodeLibrary("geometry")
    library.record("Point", [("x", int), ("y", int, default)])
    return library


@pytest.mark.parametrize("annotation", ["g.Point", "geometry.Point"])
def test_alias_annotation_is_canonical_before_check_and_inline(annotation):
    library = geometry()
    source = f"""@use "geometry" as g
@def (p: {annotation})read(x: int):
    (p)g.Point.get.x(x)
(3)g.Point.make(p)
(p)read(x)
"""
    compiled = compile_source(source, [library])
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    assert interp.source_values()["x"] == 3
    assert not [
        d
        for d in check(parse(source), build_env(parse(source), [library]))
        if d.severity == "error"
    ]


def test_unaliased_annotation_and_nominal_mismatch():
    first = geometry()
    second = NodeLibrary("drawing")
    second.record("Point", [("x", int), ("y", int, 0)])
    source = """@use "geometry" as g
@use "drawing" as d
(1)g.Point.make(p)
(p)d.Point.get.x(x)
"""
    with pytest.raises(KirCheckError, match="E040"):
        compile_source(source, [first, second])
    ambiguous = "@def (p: Point)read(x):\n    x = p\n"
    with pytest.raises(KirCheckError, match="ambiguous record type"):
        compile_source(ambiguous, [first, second])
    compile_source(ambiguous, [first])


def test_record_schema_contract_changes_identity_without_source_imports():
    source = "(1)Point.make(p)\n(p)Point.get.y(y)\n"
    before = compile_source(source, [geometry(0)])
    after = compile_source(source, [geometry(4)])
    assert before.dependencies["modules"] == []
    assert before.dependencies["signatures"]
    assert before.semantic_hash != after.semantic_hash
    assert before.dependencies != after.dependencies


def test_record_annotation_keeps_identity_through_imported_subgraph():
    module = """@use "geometry" as g
@export read
@def (p: g.Point)read(x: int):
    (p)g.Point.get.x(x)
"""
    source = """@use "geometry" as g
@import "points.kir" as points
(3)g.Point.make(p)
(p)points.read(x)
"""
    compiled = compile_source(source, [geometry()], modules={"points.kir": module})
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    assert interp.source_values()["x"] == 3


def test_missing_nested_schema_and_cross_library_cycles_are_errors():
    missing = NodeLibrary("missing")
    missing.record("Envelope", [("point", "other.Point")])
    with pytest.raises(KirSignatureError, match="unknown schema"):
        build_env(parse("x = 1\n"), [missing])
    first, second = NodeLibrary("first"), NodeLibrary("second")
    first.record("A", [("b", "second.B?")])
    second.record("B", [("a", "first.A?")])
    with pytest.raises(KirCheckError, match="recursive record schema"):
        compile_source("x = 1\n", [first, second])


def test_nested_external_schema_and_union_field_compile_and_execute():
    points = geometry()
    requests = NodeLibrary("requests")
    requests.record("Request", [("point", "geometry.Point"), ("tag", "int | str?", None)])
    source = """@use "geometry" as g
@use "requests" as r
(7)g.Point.make(p)
(p)r.Request.make(request)
(request)r.Request.get.point(q)
(q)g.Point.get.x(x)
"""
    compiled = compile_source(source, [points, requests])
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    assert interp.source_values()["x"] == 7
    assert compiled.env.record_type(parse_type("r.Request")) == parse_type("requests.Request")


def test_schema_registration_order_does_not_change_contract_identity():
    first, second = NodeLibrary("same"), NodeLibrary("same")
    for name in ("A", "B"):
        first.record(name, [("value", int)])
    for name in ("B", "A"):
        second.record(name, [("value", int)])
    assert contract_hash(first) == contract_hash(second)
    assert (
        compile_source("(1)A.make(a)\n", [first]).semantic_hash
        == compile_source("(1)A.make(a)\n", [second]).semantic_hash
    )


def test_schema_closure_includes_libraries_loaded_through_source_imports(tmp_path):
    points = geometry()
    requests = NodeLibrary("requests")
    requests.record("Request", [("point", "geometry.Point")])
    save_library(points, tmp_path / "geometry.kirsig.json")
    save_library(requests, tmp_path / "requests.kirsig.json")
    (tmp_path / "points.kir").write_text(
        '@use "geometry" as g\n@export point\n@def ()point(p: g.Point):\n    (1)g.Point.make(p)\n',
        encoding="utf-8",
    )
    source = '@use "requests" as r\n@import "points.kir" as p\n()p.point(point)\n(point)r.Request.make(request)\n'
    compiled = compile_source(source, base_dir=tmp_path, sig_path=[tmp_path])
    interpreter = Interpreter(compiled.lowered, compiled.env)
    interpreter.run()
    assert interpreter.source_values()["request"].schema_id == "requests.Request"


def test_schema_conflict_distinguishes_boolean_integer_defaults():
    first, second = NodeLibrary("same"), NodeLibrary("same")
    first.record("Value", [("value", "_", True)])
    second.record("Value", [("value", "_", 1)])
    with pytest.raises(KirCheckError, match="conflicting record schema"):
        compile_source("x = 1\n", [first, second])
