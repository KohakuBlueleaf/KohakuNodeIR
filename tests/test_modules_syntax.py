"""Source module declarations and provenance in the syntax/graph tooling surface."""

import json
from dataclasses import FrozenInstanceError, fields

import pytest

from kohakunode.errors import KirGraphError, KirSyntaxError
from kohakunode.graph import from_graph, to_graph
from kohakunode.syntax import parse, parse_file, write
from kohakunode.syntax.ast import (
    Assign,
    Import,
    Literal,
    Origin,
    Program,
    Stmt,
    TypeExpr,
    TypeHints,
    Use,
    walk,
)

SOURCE = """@export run
@import "relative/helpers.kir" as helpers
@use "host.nodes" as host
@export other
@import '../shared.kir' as shared
@mode strict

@def (x: helpers.Image)run(y: helpers.Image):
    (x)helpers.identity(y)

@def ()other(y):
    ()shared.value(y)
"""


def test_module_preamble_parse_write_and_file(tmp_path):
    program = parse(SOURCE)
    assert program.imports == [
        Import("relative/helpers.kir", "helpers"),
        Import("../shared.kir", "shared"),
    ]
    assert program.exports == ["run", "other"]
    assert program.uses == [Use("host.nodes", "host")]
    assert program.mode == "strict"
    assert program.body[0].body[0].name == "helpers.identity"
    text = write(program)
    assert text.startswith(
        '@use "host.nodes" as host\n'
        '@import "relative/helpers.kir" as helpers\n'
        '@import "../shared.kir" as shared\n'
        "@export run\n@export other\n@mode strict\n\n"
    )
    assert parse(text) == program
    assert write(parse(text)) == text
    path = tmp_path / "main.kir"
    path.write_text(SOURCE, encoding="utf-8")
    assert parse_file(path) == program


@pytest.mark.parametrize(
    "source",
    [
        '@import "helpers.kir"\n',
        '@import "helpers.kir" as\n',
        '@import "helpers.kir" as _\n',
        '@import "helpers.kir" as alias.extra\n',
        '@import "helpers.kir" asalias\n',
        '@importx "helpers.kir" as alias\n',
        "@import helpers as alias\n",
        "@export\n",
        "@export first, second\n",
        "@export first second\n",
        "@export alias.name\n",
        "@export _\n",
        "@exportx name\n",
    ],
)
def test_module_declaration_shapes_rejected(source):
    with pytest.raises(KirSyntaxError):
        parse(source)


@pytest.mark.parametrize("declaration", ['@import "h.kir" as h', "@export run", '@use "host"'])
@pytest.mark.parametrize(
    "template",
    [
        "x = 1\n{declaration}\n",
        "@meta pos=(1, 2)\n{declaration}\nx = 1\n",
        "ns:\n    {declaration}\n",
        "@def ()run():\n    {declaration}\n",
        "@dataflow:\n    {declaration}\n",
        "@try:\n    x = 1\n@except:\n    {declaration}\n",
    ],
)
def test_declarations_are_only_allowed_in_top_level_preamble(declaration, template):
    with pytest.raises(KirSyntaxError, match="only allowed at the top"):
        parse(template.format(declaration=declaration))


def test_declaration_only_and_repeated_declarations_are_syntax():
    # Duplicate/unknown exports and aliases are linker diagnostics, not syntax errors.
    program = parse('@import "a.kir" as a\n@import "b.kir" as a\n@export f\n@export f\n')
    assert program.exports == ["f", "f"]
    assert program.body == []
    assert parse(write(program)) == program
    assert parse('@use "host"\n').uses == [Use("host")]


@pytest.mark.parametrize(
    "type_text",
    ["mod.Image", "mod.Image?", "list[mod.Image]", "mod.Box[other.Item]?", "mod.Image | None"],
)
def test_qualified_nominal_types_round_trip(type_text):
    program = parse(f"x: {type_text} = None\n")
    assert write(program) == f"x: {type_text} = None\n"
    assert parse(write(program)) == program
    assert from_graph(to_graph(program), with_meta=False) == program
    if type_text == "mod.Image":
        assert program.body[0].type == TypeExpr("name", "mod.Image")


def test_ast_interfaces_preserve_positional_construction_and_equality():
    program = Program([Use("host")], [Assign("x", Literal(1))], "strict")
    assert program.imports == [] and program.exports == []
    assert [f.name for f in fields(Program)] == ["uses", "body", "mode", "imports", "exports"]
    other = Program()
    program.imports.append(Import("a.kir", "a"))
    program.exports.append("f")
    assert other.imports == [] and other.exports == []
    origin_field = next(f for f in fields(Stmt) if f.name == "origin")
    assert origin_field.kw_only and not origin_field.compare and origin_field.default is None
    origin = Origin("a.kir", "stmt_1")
    assert Assign("x", Literal(1), origin=origin, line=20) == Assign("x", Literal(1), line=1)
    assert write(Program(body=[Assign("x", Literal(1), origin=origin)])) == "x = 1\n"
    with pytest.raises(FrozenInstanceError):
        origin.module = "b.kir"
    with pytest.raises(FrozenInstanceError):
        program.imports[0].alias = "b"


@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize("with_meta", [False, True])
def test_graph_declarations_and_structured_origins(data, with_meta):
    program = parse(SOURCE)
    definition, statement = program.body[0], program.body[0].body[0]
    callsite = Origin("main.kir", "caller", 9)
    definition.origin = Origin("helpers.kir", "def_1", 1, "run")
    statement.origin = Origin("helpers.kir", "source_node", 2, "run", (callsite,), "inline")
    statement.meta = {"node_id": "editor_node", "pos": (10, 20), "origin": "editor-only"}
    graph = json.loads(json.dumps(to_graph(program, data=data)))
    assert graph["imports"] == [
        {"module": "relative/helpers.kir", "alias": "helpers"},
        {"module": "../shared.kir", "alias": "shared"},
    ]
    assert graph["exports"] == ["run", "other"]
    assert not any(n["kind"] == "import" for g in graph["graphs"] for n in g["nodes"])
    node = next(n for n in graph["graphs"][1]["nodes"] if n["kind"] == "call")
    assert node["id"] == "editor_node"
    assert node["origin"]["node_id"] == "source_node"
    assert node["origin"]["calls"][0]["node_id"] == "caller"
    assert node["meta"]["origin"] == "editor-only"
    restored = from_graph(graph, with_meta=with_meta)
    assert restored.imports == program.imports and restored.exports == program.exports
    assert restored.body[0].origin == definition.origin
    result = restored.body[0].body[0]
    assert result.origin == statement.origin
    assert isinstance(result.origin.calls, tuple)
    assert result.meta == (statement.meta if with_meta else {})
    assert result.hint == statement.hint


ORIGIN_CASES = [
    "@typehint:\n    (a.Image)f(a.Image)\n@typehint:\n    ()g(int)\nx = 1\n",
    "@def (x)f(y):\n    y = x\n(1)f(out)\n",
    "@dataflow:\n    x = 1\n    (x)f(y)\n",
    "@try:\n    ()f(x)\n@except err:\n    x = 1\n",
    "(True)branch(`yes`, `no`)\nyes:\n    x = 1\nno:\n    x = 2\n",
    "(1)switch(1=>`yes`, _=>`no`)\nyes:\n    x = 1\nno:\n    x = 2\n",
    "()parallel(`a`, `b`)\na:\n    x = 1\nb:\n    y = 2\n",
    "([1])each(item, `body`)\nbody:\n    (item)f(x)\n",
    "unused:\n    x = 1\n",
    "x = 1\n()jump(`loop`)\nloop:\n    ()f()\n    ()jump(`loop`)\n",
    "()jump(`loop`)\nloop:\n    ()f()\n    ()jump(`loop`)\n",
    "(True)branch(`a`, `b`)\na:\n    ()jump(`end`)\nb:\n    ()jump(`end`)\nend:\n    ()f()\n",
]


@pytest.mark.parametrize("source", ORIGIN_CASES)
@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize("with_meta", [False, True])
def test_graph_keeps_origins_for_all_represented_statement_kinds(source, data, with_meta):
    program = parse(source)
    for i, statement in enumerate(walk(program.body)):
        statement.origin = Origin("module.kir", f"source_{i}", statement.line)
    expected = {s.origin for s in walk(program.body)}
    graph = json.loads(json.dumps(to_graph(program, data=data)))
    restored = from_graph(graph, with_meta=with_meta)
    assert {s.origin for s in walk(restored.body) if s.origin is not None} == expected
    # Once normalized to graph topology, provenance remains stable on further round trips.
    again = from_graph(to_graph(restored, data=data), with_meta=with_meta)
    assert [s.origin for s in walk(again.body)] == [s.origin for s in walk(restored.body)]
    # Text has no provenance syntax. Editor metadata still follows with_meta.
    text = write(restored)
    erased = parse(text)
    assert all(s.origin is None for s in walk(erased.body))
    hints = [s for s in erased.body if isinstance(s, TypeHints)]
    if len(hints) > 1:
        # Legacy no-origin graph projection merges typehint blocks. Erasing
        # their distinct origins permits that one extra normalization step.
        erased.body = [TypeHints([e for h in hints for e in h.entries])] + [
            s for s in erased.body if not isinstance(s, TypeHints)
        ]
        text = write(erased)
    normalized = from_graph(to_graph(parse(write(restored)), data=data), with_meta=with_meta)
    assert write(normalized) == text
    assert write(from_graph(to_graph(parse(text), data=data), with_meta=with_meta)) == text


@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize("with_origins", [False, True])
def test_root_each_round_trip_is_independent_of_provenance(data, with_origins):
    program = parse("([1])each(item, `body`)\nbody:\n    x = item\n")
    if with_origins:
        for i, statement in enumerate(walk(program.body)):
            statement.origin = Origin("m.kir", str(i))
    assert from_graph(to_graph(program, data=data), with_meta=False) == program


@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize("with_origins", [False, True])
@pytest.mark.parametrize("back_edge", [False, True])
def test_explicit_jump_entry_marker_distinguishes_unentered_namespace(
    data, with_origins, back_edge
):
    namespace = "loop:\n    x = 1\n" + ("    ()jump(`loop`)\n" if back_edge else "")
    entered = parse("()jump(`loop`)\n" + namespace)
    unentered = parse(namespace)
    if with_origins:
        for program in (entered, unentered):
            for i, statement in enumerate(walk(program.body)):
                statement.origin = Origin("m.kir", str(i))
    entered_graph = to_graph(entered, data=data)
    unentered_graph = to_graph(unentered, data=data)
    merge = next(n for n in entered_graph["graphs"][0]["nodes"] if n["kind"] == "merge")
    assert merge["entry"] is True
    assert all("entry" not in n for n in unentered_graph["graphs"][0]["nodes"])
    assert from_graph(entered_graph, with_meta=False) == entered
    assert from_graph(unentered_graph, with_meta=False) == unentered
    # A pre-marker graph cannot disambiguate these programs. Conservatively
    # reconstruct only the namespace, even if an origin happens to be present.
    del merge["entry"]
    assert from_graph(entered_graph, with_meta=False) == unentered


def test_graph_shape_has_no_empty_fields():
    assert to_graph(parse("x = 1\n")) == {
        "kirgraph": 3,
        "uses": [],
        "graphs": [
            {
                "name": "main",
                "nodes": [
                    {
                        "id": "assign_1",
                        "kind": "assign",
                        "inputs": [{"port": "value", "value": 1}],
                        "outputs": [{"port": "value", "var": "x"}],
                        "ctrl_in": ["in"],
                        "ctrl_out": ["out"],
                        "path": "body/0",
                    }
                ],
                "edges": [],
            }
        ],
    }


@pytest.mark.parametrize(
    "origin",
    [
        "text",
        {},
        {"module": "a", "node_id": 1},
        {"module": "a", "node_id": "n", "line": "1"},
        {"module": "a", "node_id": "n", "calls": [None]},
        {"module": "a", "node_id": "n", "calls": "bad"},
        {"module": "a", "node_id": "n", "generated": []},
    ],
)
def test_graph_rejects_malformed_structured_origin(origin):
    graph = to_graph(parse("x = 1\n"))
    graph["graphs"][0]["nodes"][0]["origin"] = origin
    with pytest.raises(KirGraphError, match="origin"):
        from_graph(graph, with_meta=False)
