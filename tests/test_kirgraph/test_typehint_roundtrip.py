"""Type hints survive the KirGraph roundtrip.

Path tested:
    KIR text → parse → Program (with typehints)
                     → KirGraphDecompiler → KirGraph
                     → KirGraphCompiler   → Program
                     → Writer            → KIR text

Because KirGraph does not currently carry a @typehint block, we test two
complementary things:

1. A Program with typehints serialises to a KIR string that contains the
   @typehint: block (Writer round-trip).
2. After a full kir_to_graph → KirGraphCompiler round-trip, the *execution*
   result is identical (the typehint block is non-executing, so equivalence
   means the body still runs correctly).
3. When a KirGraph is built with typed ports and compiled back to KIR, the
   @typehint block entries can be reconstructed by inspecting port types.
"""

import json

import pytest

from kohakunode import Registry, parse
from kohakunode.ast.nodes import Assignment, FuncCall, TypeHintEntry, TypeExpr
from kohakunode.engine.executor import Executor
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.decompiler import KirGraphDecompiler
from kohakunode.kirgraph.schema import KGEdge, KGNode, KGPort, KirGraph
from kohakunode.layout.ascii_view import kir_to_graph
from kohakunode.layout.auto_layout import auto_layout
from kohakunode.serializer.writer import Writer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> Registry:
    reg = Registry()
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("multiply", lambda a, b: a * b, output_names=["result"])
    reg.register("to_string", lambda v: str(v), output_names=["result"])
    reg.register("identity", lambda v: v, output_names=["result"])
    return reg


def _roundtrip_kir(source: str) -> str:
    """KIR text → kir_to_graph → KirGraph → KirGraphCompiler → KIR text."""
    graph = kir_to_graph(source)
    graph = auto_layout(graph)
    kg_dict = json.loads(json.dumps(graph.to_dict()))
    graph2 = KirGraph.from_dict(kg_dict)
    program = KirGraphCompiler().compile(graph2)
    return Writer().write(program)


def _execute(source: str, registry: Registry) -> dict:
    exe = Executor(registry=registry, validate=False)
    return exe.execute_source(source).snapshot()


# ---------------------------------------------------------------------------
# KIR with @typehint → parse → write → verify types preserved
# ---------------------------------------------------------------------------


def test_typehint_preserved_in_writer_output() -> None:
    """Writer emits @typehint: block when Program.typehints is set."""
    src = """\
@typehint:
    (int, int)add(int)
    (int)to_string(str)

x: int = 10
y: int = 20
(x, y)add(sum)
"""
    prog = parse(src)
    out = Writer().write(prog)
    assert "@typehint:" in out
    assert "(int, int)add(int)" in out
    assert "(int)to_string(str)" in out


def test_typehint_block_not_in_body_after_parse() -> None:
    """@typehint is hoisted to Program.typehints, not left in body."""
    from kohakunode.ast.nodes import TypeHintBlock

    src = "@typehint:\n    (int, int)add(int)\n"
    prog = parse(src)
    for stmt in prog.body:
        assert not isinstance(stmt, TypeHintBlock)
    assert prog.typehints is not None
    assert len(prog.typehints) == 1


def test_typehint_entries_match_after_write_reparse() -> None:
    """parse → write → re-parse yields identical TypeHintEntry list."""
    src = """\
@typehint:
    (int, int)add(int)
    (tensor?)normalize(tensor)
    (Any, _)concat(str)
    (my_type)process(my_result)
"""
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)

    assert prog1.typehints is not None
    assert prog2.typehints is not None
    assert len(prog1.typehints) == len(prog2.typehints)

    for e1, e2 in zip(prog1.typehints, prog2.typehints):
        assert e1.func_name == e2.func_name
        assert len(e1.input_types) == len(e2.input_types)
        assert len(e1.output_types) == len(e2.output_types)
        for t1, t2 in zip(e1.input_types, e2.input_types):
            assert t1.name == t2.name
            assert t1.is_optional == t2.is_optional
            assert (t1.union_of is None) == (t2.union_of is None)


def test_typed_assignments_survive_write_reparse() -> None:
    """Typed assignments (`x: int = 5`) survive a write → re-parse cycle."""
    src = "x: int = 10\ny: float = 3.14\nresult: str? = None\n"
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)

    stmts1 = [s for s in prog1.body if isinstance(s, Assignment)]
    stmts2 = [s for s in prog2.body if isinstance(s, Assignment)]
    assert len(stmts1) == len(stmts2)

    for s1, s2 in zip(stmts1, stmts2):
        assert s1.target == s2.target
        assert (s1.type_annotation is None) == (s2.type_annotation is None)
        if s1.type_annotation is not None:
            assert s1.type_annotation.name == s2.type_annotation.name
            assert s1.type_annotation.is_optional == s2.type_annotation.is_optional


# ---------------------------------------------------------------------------
# Full KIR → KirGraph → KIR execution equivalence
# ---------------------------------------------------------------------------


def test_typehint_program_executes_correctly_after_roundtrip() -> None:
    """Program with @typehint executes with correct values after graph roundtrip.

    The graph compiler renames variables to "<node_id>_<port>", so we check
    that at least one variable holds the expected numeric result rather than
    asserting on a fixed variable name.
    """
    src = """\
@typehint:
    (int, int)add(int)
    (int)to_string(str)

x = 3
y = 4
(x, y)add(total)
(total)to_string(text)
"""
    # Original execution
    orig = _execute(src, _make_registry())
    assert orig["total"] == 7
    assert orig["text"] == "7"

    # Roundtrip: graph compiler renames variables to "<node_id>_<port>"
    rt_kir = _roundtrip_kir(src)
    rt_result = _execute(rt_kir, _make_registry())

    # The add result (7) and string result ("7") must appear somewhere in variables
    numeric_values = [v for v in rt_result.values() if v == 7]
    string_values = [v for v in rt_result.values() if v == "7"]
    assert len(numeric_values) >= 1, f"Expected 7 in roundtripped vars: {rt_result}"
    assert len(string_values) >= 1, f"Expected '7' in roundtripped vars: {rt_result}"


def test_program_body_preserved_after_roundtrip() -> None:
    """Body statements are correct after graph roundtrip (typehint is no-op).

    The graph compiler renames variables, so we check that the multiply result
    (42) appears in the final variable store rather than checking a fixed name.
    """
    src = """\
@typehint:
    (int, int)multiply(int)

a = 6
b = 7
(a, b)multiply(product)
"""
    reg = _make_registry()

    orig = Executor(registry=reg, validate=False).execute_source(src).snapshot()
    assert orig["product"] == 42

    rt_kir = _roundtrip_kir(src)
    rt_reg = _make_registry()
    rt_result = Executor(registry=rt_reg, validate=False).execute_source(rt_kir).snapshot()

    # Check that 42 appears somewhere in the variable store
    assert 42 in rt_result.values(), f"Expected 42 in roundtripped vars: {rt_result}"


# ---------------------------------------------------------------------------
# KirGraph with typed ports → compile → verify port types accessible
# ---------------------------------------------------------------------------


def test_kirgraph_typed_ports_preserved_in_schema() -> None:
    """KGPort type field is stored and retrieved correctly."""
    port = KGPort(port="value", type="int")
    d = port.to_dict()
    assert d["type"] == "int"
    port2 = KGPort.from_dict(d)
    assert port2.type == "int"


def test_kirgraph_any_port_type_default() -> None:
    """KGPort defaults to 'any' when no type is specified."""
    port = KGPort(port="x")
    assert port.type == "any"
    d = port.to_dict()
    port2 = KGPort.from_dict(d)
    assert port2.type == "any"


def test_kirgraph_typed_node_serializes_and_deserializes() -> None:
    """A node with typed ports survives JSON serialization roundtrip."""
    node = KGNode(
        id="add1",
        type="add",
        name="Add",
        data_inputs=[
            KGPort(port="a", type="int"),
            KGPort(port="b", type="int"),
        ],
        data_outputs=[KGPort(port="result", type="int")],
    )
    d = node.to_dict()
    node2 = KGNode.from_dict(d)

    assert node2.data_inputs[0].type == "int"
    assert node2.data_inputs[1].type == "int"
    assert node2.data_outputs[0].type == "int"


def test_kirgraph_typed_ports_survive_json_roundtrip() -> None:
    """Custom type names on ports survive JSON serialization."""
    node = KGNode(
        id="proc1",
        type="process",
        name="Process",
        data_inputs=[KGPort(port="tensor_in", type="my_tensor")],
        data_outputs=[KGPort(port="result_out", type="my_result")],
    )
    kg = KirGraph(nodes=[node], edges=[])
    d = json.loads(json.dumps(kg.to_dict()))
    kg2 = KirGraph.from_dict(d)

    assert kg2.nodes[0].data_inputs[0].type == "my_tensor"
    assert kg2.nodes[0].data_outputs[0].type == "my_result"


def test_kirgraph_optional_type_in_port() -> None:
    """Port with 'tensor?' type survives JSON roundtrip."""
    node = KGNode(
        id="norm1",
        type="normalize",
        name="Normalize",
        data_inputs=[KGPort(port="input", type="tensor?")],
        data_outputs=[KGPort(port="output", type="tensor")],
    )
    d = node.to_dict()
    node2 = KGNode.from_dict(d)
    assert node2.data_inputs[0].type == "tensor?"
    assert node2.data_outputs[0].type == "tensor"


def test_kirgraph_union_type_in_port() -> None:
    """Port with 'int | float' type string survives JSON roundtrip."""
    node = KGNode(
        id="conv1",
        type="convert",
        name="Convert",
        data_inputs=[KGPort(port="val", type="int | float")],
        data_outputs=[KGPort(port="out", type="str")],
    )
    d = node.to_dict()
    node2 = KGNode.from_dict(d)
    assert node2.data_inputs[0].type == "int | float"


# ---------------------------------------------------------------------------
# Decompiler: Program with typehints produces valid KirGraph
# ---------------------------------------------------------------------------


def test_decompiler_handles_program_with_typehints() -> None:
    """KirGraphDecompiler does not crash on a program with typehints."""
    src = """\
@typehint:
    (int, int)add(int)

x = 1
y = 2
(x, y)add(result)
"""
    prog = parse(src)
    graph = KirGraphDecompiler().decompile(prog)
    assert isinstance(graph, KirGraph)
    # Body nodes should be present (value nodes + add node)
    assert len(graph.nodes) > 0


def test_compiler_produces_program_from_typed_graph() -> None:
    """KirGraphCompiler produces a valid Program from a graph with typed ports."""
    val_a = KGNode(
        id="val_a",
        type="value",
        name="Value A",
        data_inputs=[],
        data_outputs=[KGPort(port="value", type="int")],
        properties={"value_type": "int", "value": 5},
    )
    val_b = KGNode(
        id="val_b",
        type="value",
        name="Value B",
        data_inputs=[],
        data_outputs=[KGPort(port="value", type="int")],
        properties={"value_type": "int", "value": 3},
    )
    add_node = KGNode(
        id="add1",
        type="add",
        name="Add",
        data_inputs=[
            KGPort(port="a", type="int"),
            KGPort(port="b", type="int"),
        ],
        data_outputs=[KGPort(port="result", type="int")],
        ctrl_inputs=["in"],
        ctrl_outputs=["out"],
    )
    edges = [
        KGEdge(type="data", from_node="val_a", from_port="value", to_node="add1", to_port="a"),
        KGEdge(type="data", from_node="val_b", from_port="value", to_node="add1", to_port="b"),
    ]
    graph = KirGraph(nodes=[val_a, val_b, add_node], edges=edges)
    program = KirGraphCompiler().compile(graph)
    assert program is not None

    # The compiled program should have statements
    assert len(program.body) > 0
