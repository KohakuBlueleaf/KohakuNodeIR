"""Signature-only nested records: reference/lowering/graph equivalence and alias safety."""

import json
from pathlib import Path

from kohakunode import (
    Interpreter,
    check,
    compile_file,
    compile_program,
    construct,
    decode_record,
    encode_record,
    project,
    replace_field,
)
from kohakunode.graph import from_graph, to_graph
from kohakunode.lower import PASSES, run_passes
from kohakunode.records import RecordOperation
from kohakunode.sig import load_library

HERE = Path(__file__).resolve().parent
SUMMARY = {
    "original_x": 1.0,
    "updated_x": 3.0,
    "default_y": 0.0,
    "nullable_label": None,
    "nullable_fallback": None,
    "original_tags": ["input"],
    "reviewed_tags": ["input", "reviewed"],
}


def execute(program, env):
    interpreter = Interpreter(program, env)
    interpreter.run()
    return interpreter.source_values()


def alias_demo(library) -> None:
    """Both construction and replacement snapshot; projection returns a fresh list."""
    point_schema = library.records["Point"]
    request_schema = library.records["Request"]
    point = construct(point_schema, x=1.0)
    source_tags = ["input"]
    request = construct(request_schema, id="alias-check", point=point, tags=source_tags)
    source_tags.append("outside")
    projected = project(request_schema, request, "tags")
    projected.append("local")
    assert project(request_schema, request, "tags") == ["input"]
    replacement = ["new"]
    updated = replace_field(request_schema, request, "tags", replacement)
    replacement.append("outside")
    assert project(request_schema, updated, "tags") == ["new"]
    assert project(request_schema, request, "tags") == ["input"]
    assert project(request_schema, request, "point") is point
    registry = {schema.schema_id: schema for schema in library.records.values()}
    restored = decode_record(json.loads(json.dumps(encode_record(updated))), registry)
    assert restored == updated
    assert restored.__togeari_digest__() == updated.__togeari_digest__()
    print("alias safety: input, projection and replacement lists are independent")
    print("codec: nested Request/Point roundtrip and digest match")


def main() -> None:
    library = load_library(HERE / "geometry.kirsig.json")
    assert library.impls and all(type(impl) is RecordOperation for impl in library.impls.values())
    compiled = compile_file(HERE / "main.kir")
    assert not [
        diagnostic
        for diagnostic in check(compiled.program, compiled.env)
        if diagnostic.severity == "error"
    ]
    expected = execute(compiled.program, compiled.env)
    assert {name: expected[name] for name in SUMMARY} == SUMMARY
    for count in range(len(PASSES) + 1):
        partial = run_passes(compiled.program, compiled.env, list(PASSES)[:count])
        assert execute(partial, compiled.env) == expected
    print("signature-only: generated operations, no imported host implementation")
    print("reference: every lowering pass prefix agrees")
    for style in ("wires", "variables"):
        graph = to_graph(compiled.program, compiled.env, data=style)
        calls = [
            node for scope in graph["graphs"] for node in scope["nodes"] if node["kind"] == "call"
        ]
        assert any(node["name"] == "g.Request.get.point" for node in calls)
        assert any(node["name"] == "g.Point.with.x" for node in calls)
        assert all(node.get("origin") is not None for node in calls)
        restored = from_graph(json.loads(json.dumps(graph)))
        rebuilt = compile_program(restored, base_dir=HERE, sig_path=[HERE])
        assert execute(rebuilt.lowered, rebuilt.env) == expected
    print("graph: wires and variables roundtrips agree; get/with nodes retain origins")
    print(json.dumps(SUMMARY, sort_keys=True))
    alias_demo(library)


if __name__ == "__main__":
    main()
