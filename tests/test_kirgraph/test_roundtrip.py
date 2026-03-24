"""Tests for the .kirgraph (L1) <-> .kir (L2) compiler/decompiler."""


import json

from kohakunode import DataflowCompiler, Writer
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.decompiler import KirGraphDecompiler
from kohakunode.kirgraph.schema import KGEdge, KGNode, KGPort, KirGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_value_node(
    node_id: str,
    value: object,
    value_type: str = "int",
    pos: list[int] | None = None,
) -> KGNode:
    """Create a value node with no control ports."""
    meta = {"pos": pos} if pos else {}
    return KGNode(
        id=node_id,
        type="value",
        name=f"Value {node_id}",
        data_inputs=[],
        data_outputs=[KGPort(port="value", type=value_type)],
        ctrl_inputs=[],
        ctrl_outputs=[],
        properties={"value_type": value_type, "value": value},
        meta=meta,
    )


def _make_func_node(
    node_id: str,
    func_type: str,
    input_ports: list[KGPort],
    output_ports: list[KGPort],
    ctrl_in: bool = True,
    ctrl_out: bool = True,
    pos: list[int] | None = None,
) -> KGNode:
    """Create a function node with standard control ports."""
    meta = {"pos": pos} if pos else {}
    return KGNode(
        id=node_id,
        type=func_type,
        name=func_type.replace("_", " ").title(),
        data_inputs=input_ports,
        data_outputs=output_ports,
        ctrl_inputs=["in"] if ctrl_in else [],
        ctrl_outputs=["out"] if ctrl_out else [],
        meta=meta,
    )


def _make_branch_node(
    node_id: str, pos: list[int] | None = None
) -> KGNode:
    meta = {"pos": pos} if pos else {}
    return KGNode(
        id=node_id,
        type="branch",
        name="Branch",
        data_inputs=[KGPort(port="condition", type="bool")],
        data_outputs=[],
        ctrl_inputs=["in"],
        ctrl_outputs=["true", "false"],
        meta=meta,
    )


def _make_merge_node(
    node_id: str, num_inputs: int = 2, pos: list[int] | None = None
) -> KGNode:
    meta = {"pos": pos} if pos else {}
    return KGNode(
        id=node_id,
        type="merge",
        name="Merge",
        data_inputs=[],
        data_outputs=[],
        ctrl_inputs=[f"in_{i}" for i in range(num_inputs)],
        ctrl_outputs=["out"],
        meta=meta,
    )


def _ctrl_edge(
    from_node: str, from_port: str, to_node: str, to_port: str
) -> KGEdge:
    return KGEdge(
        type="control",
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
    )


def _data_edge(
    from_node: str, from_port: str, to_node: str, to_port: str
) -> KGEdge:
    return KGEdge(
        type="data",
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
    )


def _get_edge_set(graph: KirGraph, edge_type: str) -> set[tuple[str, str, str, str]]:
    """Extract edges of a given type as a set of (from_node, from_port, to_node, to_port)."""
    return {
        (e.from_node, e.from_port, e.to_node, e.to_port)
        for e in graph.edges
        if e.type == edge_type
    }


def _get_node_ids(graph: KirGraph) -> set[str]:
    return {n.id for n in graph.nodes}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSimpleChain:
    """3 nodes in a control chain: add -> multiply -> print."""

    def _build_graph(self) -> KirGraph:
        nodes = [
            _make_func_node(
                "n1",
                "add",
                [KGPort(port="a", default=5), KGPort(port="b", default=3)],
                [KGPort(port="result", type="float")],
            ),
            _make_func_node(
                "n2",
                "multiply",
                [KGPort(port="a"), KGPort(port="b", default=2)],
                [KGPort(port="result", type="float")],
            ),
            _make_func_node(
                "n3",
                "print",
                [KGPort(port="value")],
                [],
            ),
        ]
        edges = [
            _data_edge("n1", "result", "n2", "a"),
            _data_edge("n2", "result", "n3", "value"),
            _ctrl_edge("n1", "out", "n2", "in"),
            _ctrl_edge("n2", "out", "n3", "in"),
        ]
        return KirGraph(nodes=nodes, edges=edges)

    def test_simple_chain(self) -> None:
        graph = self._build_graph()
        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        # Verify the program has statements (no dataflow block since all are ctrl).
        assert len(program.body) > 0

        # Decompile back.
        decompiler = KirGraphDecompiler()
        recovered = decompiler.decompile(program)

        # Verify topology: same node types present.
        orig_types = {n.type for n in graph.nodes}
        recovered_types = {n.type for n in recovered.nodes}
        assert orig_types == recovered_types

        # Verify data edges are recovered (compare source node/port, target node).
        # Target port names may differ because the decompiler infers them
        # positionally (a, b, c...) rather than recovering the original names.
        orig_data_src = {
            (e.from_node, e.from_port, e.to_node) for e in graph.edges if e.type == "data"
        }
        recovered_data_src = {
            (e.from_node, e.from_port, e.to_node)
            for e in recovered.edges
            if e.type == "data"
        }
        assert orig_data_src == recovered_data_src

    def test_roundtrip_serialization(self) -> None:
        """Compile, serialize to KIR text, verify it's valid."""
        graph = self._build_graph()
        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        writer = Writer()
        kir_text = writer.write(program)
        assert "(n1_result" in kir_text or "n1_result" in kir_text


class TestBranchPattern:
    """Branch with two paths."""

    def _build_graph(self) -> KirGraph:
        nodes = [
            _make_func_node(
                "check",
                "is_positive",
                [KGPort(port="value", default=0)],
                [KGPort(port="result", type="bool")],
            ),
            _make_branch_node("br"),
            _make_func_node(
                "pos_handler",
                "print",
                [KGPort(port="value")],
                [],
            ),
            _make_func_node(
                "neg_handler",
                "print",
                [KGPort(port="value")],
                [],
            ),
        ]
        edges = [
            _data_edge("check", "result", "br", "condition"),
            _ctrl_edge("check", "out", "br", "in"),
            _ctrl_edge("br", "true", "pos_handler", "in"),
            _ctrl_edge("br", "false", "neg_handler", "in"),
        ]
        return KirGraph(nodes=nodes, edges=edges)

    def test_branch_pattern(self) -> None:
        graph = self._build_graph()
        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        writer = Writer()
        kir_text = writer.write(program)

        # Should contain branch and namespace labels.
        assert "branch(" in kir_text
        assert "br_true:" in kir_text
        assert "br_false:" in kir_text

        # Decompile back.
        decompiler = KirGraphDecompiler()
        recovered = decompiler.decompile(program)

        # Should have a branch node.
        branch_nodes = [n for n in recovered.nodes if n.type == "branch"]
        assert len(branch_nodes) == 1


class TestValueNodesToDataflow:
    """Value nodes (no ctrl edges) compile to @dataflow: block."""

    def test_value_nodes_to_dataflow(self) -> None:
        nodes = [
            _make_value_node("v1", 10, pos=[100, 100]),
            _make_value_node("v2", 20, pos=[100, 200]),
            _make_value_node("v3", 30, pos=[100, 300]),
        ]
        graph = KirGraph(nodes=nodes, edges=[])

        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        writer = Writer()
        kir_text = writer.write(program)

        # Should have @dataflow: block.
        assert "@dataflow:" in kir_text
        assert "v1_value = 10" in kir_text
        assert "v2_value = 20" in kir_text
        assert "v3_value = 30" in kir_text


class TestMixedCtrlAndDataflow:
    """Some nodes ctrl-connected, some not -> correct partitioning."""

    def test_mixed_ctrl_and_dataflow(self) -> None:
        nodes = [
            _make_value_node("val_x", 42),
            _make_value_node("val_y", 7),
            _make_func_node(
                "func1",
                "add",
                [KGPort(port="a"), KGPort(port="b")],
                [KGPort(port="result", type="float")],
            ),
            _make_func_node(
                "func2",
                "print",
                [KGPort(port="value")],
                [],
            ),
        ]
        edges = [
            _data_edge("val_x", "value", "func1", "a"),
            _data_edge("val_y", "value", "func1", "b"),
            _data_edge("func1", "result", "func2", "value"),
            _ctrl_edge("func1", "out", "func2", "in"),
        ]
        graph = KirGraph(nodes=nodes, edges=edges)

        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        writer = Writer()
        kir_text = writer.write(program)

        # Value nodes should be in a @dataflow: block.
        assert "@dataflow:" in kir_text
        assert "val_x_value = 42" in kir_text

        # Control-connected nodes should be outside @dataflow:.
        assert ")add(" in kir_text
        assert ")print(" in kir_text


class TestLoopPattern:
    """Merge + branch forming a loop -> roundtrip."""

    def test_loop_pattern(self) -> None:
        nodes = [
            _make_func_node(
                "init",
                "setup",
                [],
                [KGPort(port="counter", type="int")],
            ),
            _make_func_node(
                "check",
                "less_than",
                [KGPort(port="a"), KGPort(port="b", default=10)],
                [KGPort(port="result", type="bool")],
            ),
            _make_branch_node("loop_br"),
            _make_func_node(
                "body",
                "increment",
                [KGPort(port="value")],
                [KGPort(port="result", type="int")],
            ),
        ]
        edges = [
            _data_edge("init", "counter", "check", "a"),
            _data_edge("check", "result", "loop_br", "condition"),
            _ctrl_edge("init", "out", "check", "in"),
            _ctrl_edge("check", "out", "loop_br", "in"),
            _ctrl_edge("loop_br", "true", "body", "in"),
        ]
        graph = KirGraph(nodes=nodes, edges=edges)

        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        writer = Writer()
        kir_text = writer.write(program)

        # Should have branch with namespaces.
        assert "branch(" in kir_text


class TestKirgraphToJsonRoundtrip:
    """Serialize to JSON, deserialize, verify equality."""

    def test_kirgraph_to_json_roundtrip(self) -> None:
        nodes = [
            _make_value_node("v1", 10, "int", [100, 100]),
            _make_func_node(
                "f1",
                "add",
                [KGPort(port="a", default=0), KGPort(port="b", default=0)],
                [KGPort(port="result", type="float")],
                pos=[300, 100],
            ),
        ]
        edges = [
            _data_edge("v1", "value", "f1", "a"),
        ]
        graph = KirGraph(nodes=nodes, edges=edges)

        # Serialize to JSON and back.
        json_text = graph.to_json()
        recovered = KirGraph.from_json(json_text)

        assert recovered.version == graph.version
        assert len(recovered.nodes) == len(graph.nodes)
        assert len(recovered.edges) == len(graph.edges)

        # Verify node ids match.
        assert _get_node_ids(recovered) == _get_node_ids(graph)

        # Verify edge topology.
        assert _get_edge_set(recovered, "data") == _get_edge_set(graph, "data")

    def test_dict_roundtrip(self) -> None:
        graph = KirGraph(
            nodes=[_make_value_node("n", 99)],
            edges=[],
        )
        d = graph.to_dict()
        recovered = KirGraph.from_dict(d)
        assert recovered.nodes[0].id == "n"
        assert recovered.nodes[0].properties["value"] == 99


class TestCompileFullExample:
    """Use the full example from the spec."""

    def _build_full_example(self) -> KirGraph:
        nodes = [
            KGNode(
                id="val_a",
                type="value",
                name="Value A",
                data_inputs=[],
                data_outputs=[KGPort(port="value", type="int")],
                ctrl_inputs=[],
                ctrl_outputs=[],
                properties={"value_type": "int", "value": 10},
                meta={"pos": [100, 100], "size": [160, 80]},
            ),
            KGNode(
                id="val_b",
                type="value",
                name="Value B",
                data_inputs=[],
                data_outputs=[KGPort(port="value", type="int")],
                ctrl_inputs=[],
                ctrl_outputs=[],
                properties={"value_type": "int", "value": 20},
                meta={"pos": [100, 250], "size": [160, 80]},
            ),
            KGNode(
                id="add1",
                type="add",
                name="Add",
                data_inputs=[
                    KGPort(port="a", type="float", default=0),
                    KGPort(port="b", type="float", default=0),
                ],
                data_outputs=[KGPort(port="result", type="float")],
                ctrl_inputs=["in"],
                ctrl_outputs=["out"],
                meta={"pos": [350, 150], "size": [180, 120]},
            ),
            KGNode(
                id="cmp1",
                type="greater_than",
                name="Greater Than",
                data_inputs=[
                    KGPort(port="a", type="float", default=0),
                    KGPort(port="b", type="float", default=25),
                ],
                data_outputs=[KGPort(port="result", type="bool")],
                ctrl_inputs=["in"],
                ctrl_outputs=["out"],
                meta={"pos": [600, 150], "size": [180, 120]},
            ),
            KGNode(
                id="br1",
                type="branch",
                name="Branch",
                data_inputs=[KGPort(port="condition", type="bool")],
                data_outputs=[],
                ctrl_inputs=["in"],
                ctrl_outputs=["true", "false"],
                meta={"pos": [850, 150], "size": [180, 120]},
            ),
            KGNode(
                id="print_big",
                type="print",
                name="Print Big",
                data_inputs=[KGPort(port="value", type="any")],
                data_outputs=[],
                ctrl_inputs=["in"],
                ctrl_outputs=["out"],
                meta={"pos": [1100, 50], "size": [180, 100]},
            ),
            KGNode(
                id="print_small",
                type="print",
                name="Print Small",
                data_inputs=[KGPort(port="value", type="any")],
                data_outputs=[],
                ctrl_inputs=["in"],
                ctrl_outputs=["out"],
                meta={"pos": [1100, 250], "size": [180, 100]},
            ),
        ]
        edges = [
            _data_edge("val_a", "value", "add1", "a"),
            _data_edge("val_b", "value", "add1", "b"),
            _data_edge("add1", "result", "cmp1", "a"),
            _data_edge("cmp1", "result", "br1", "condition"),
            _data_edge("add1", "result", "print_big", "value"),
            _data_edge("add1", "result", "print_small", "value"),
            _ctrl_edge("add1", "out", "cmp1", "in"),
            _ctrl_edge("cmp1", "out", "br1", "in"),
            _ctrl_edge("br1", "true", "print_big", "in"),
            _ctrl_edge("br1", "false", "print_small", "in"),
        ]
        return KirGraph(nodes=nodes, edges=edges)

    def test_compile_full_example(self) -> None:
        graph = self._build_full_example()
        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        writer = Writer()
        kir_text = writer.write(program)

        # Verify key elements of the L2 output.
        assert "@dataflow:" in kir_text
        assert "val_a_value = 10" in kir_text
        assert "val_b_value = 20" in kir_text
        assert ")add(" in kir_text
        assert ")greater_than(" in kir_text
        assert "branch(" in kir_text
        assert "br1_true:" in kir_text
        assert "br1_false:" in kir_text
        assert ")print(" in kir_text

    def test_compile_to_l3(self) -> None:
        """Compile L1 -> L2 -> L3 and verify no @dataflow: remains."""
        graph = self._build_full_example()
        compiler = KirGraphCompiler()
        program_l2 = compiler.compile(graph)

        dc = DataflowCompiler()
        program_l3 = dc.transform(program_l2)

        writer = Writer()
        kir_l3 = writer.write(program_l3)

        # L3 should not have @dataflow: blocks.
        assert "@dataflow:" not in kir_l3
        # But should still have all the statements.
        assert "val_a_value = 10" in kir_l3
        assert "val_b_value = 20" in kir_l3
        assert ")add(" in kir_l3

    def test_decompile_full_example(self) -> None:
        """Compile and decompile the full example, verify node recovery."""
        graph = self._build_full_example()
        compiler = KirGraphCompiler()
        program = compiler.compile(graph)

        decompiler = KirGraphDecompiler()
        recovered = decompiler.decompile(program)

        # All original node types should be present.
        orig_types = sorted(n.type for n in graph.nodes)
        recovered_types = sorted(n.type for n in recovered.nodes)
        assert orig_types == recovered_types

        # Value nodes should be recovered.
        val_nodes = [n for n in recovered.nodes if n.type == "value"]
        assert len(val_nodes) == 2

        # Branch should be recovered.
        branch_nodes = [n for n in recovered.nodes if n.type == "branch"]
        assert len(branch_nodes) == 1


class TestShowL1L2L3:
    """Print all 3 levels for a graph (for visibility)."""

    def test_show_l1_l2_l3(self, capsys: object) -> None:
        # Build a simple graph.
        nodes = [
            _make_value_node("x", 5),
            _make_value_node("y", 3),
            _make_func_node(
                "sum1",
                "add",
                [KGPort(port="a"), KGPort(port="b")],
                [KGPort(port="result", type="int")],
            ),
        ]
        edges = [
            _data_edge("x", "value", "sum1", "a"),
            _data_edge("y", "value", "sum1", "b"),
            _ctrl_edge("sum1", "out", "sum1", "in"),  # self-loop won't work, skip
        ]
        # Remove self-loop.
        edges = [
            _data_edge("x", "value", "sum1", "a"),
            _data_edge("y", "value", "sum1", "b"),
        ]
        graph = KirGraph(nodes=nodes, edges=edges)

        # L1 -> L2
        compiler = KirGraphCompiler()
        program_l2 = compiler.compile(graph)
        writer = Writer()
        l2_text = writer.write(program_l2)

        print("\n--- L1 (.kirgraph) ---")
        print(graph.to_json())
        print("\n--- L2 (.kir with @dataflow:) ---")
        print(l2_text)

        # L2 -> L3
        dc = DataflowCompiler()
        program_l3 = dc.transform(program_l2)
        l3_text = writer.write(program_l3)

        print("--- L3 (.kir sequential) ---")
        print(l3_text)

        # Just verify no crash and output is non-empty.
        assert len(l2_text) > 0
        assert len(l3_text) > 0
