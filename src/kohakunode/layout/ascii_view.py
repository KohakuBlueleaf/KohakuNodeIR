"""ASCII graph viewer for KIR programs.

Parses a .kir file, extracts nodes + edges, and prints a human-readable
text representation showing the graph structure.

Usage:
    python -m kohakunode.layout.ascii_view examples/kir_basics/mixed_mode.kir
"""

import sys
from pathlib import Path

from kohakunode import parse
from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    FuncCall,
    Identifier,
    Jump,
    Literal,
    Namespace,
    Parallel,
    Statement,
    Switch,
)
from kohakunode.kirgraph.schema import KGEdge, KGNode, KGPort, KirGraph
from kohakunode.layout.auto_layout import auto_layout
from kohakunode.layout.score import score_layout


def kir_to_graph(source: str) -> KirGraph:
    """Parse KIR source → extract nodes + edges directly from AST.

    Unlike the decompiler (which relies on {node_id}_{port} variable naming),
    this builds the graph by tracking ALL variable definitions and usages,
    handling plain variable names like 'counter', 'total' etc.
    """
    prog = parse(source)
    nodes: list[KGNode] = []
    edges: list[KGEdge] = []
    node_counter = 0
    # var_name → (node_id, port_name) — tracks which node produces each variable
    var_source: dict[str, tuple[str, str]] = {}

    def gen_id(prefix: str) -> str:
        nonlocal node_counter
        node_counter += 1
        return f"{prefix}_{node_counter}"

    # namespace_label → first node id inside that namespace
    ns_first_node: dict[str, str | None] = {}
    # jump targets for creating ctrl edges after full walk
    jump_wires: list[tuple[str | None, str]] = []  # (from_ctrl_id, target_label)

    def make_func_node(stmt: FuncCall, in_dataflow: bool) -> str:
        """Create a FuncCall node, wire data edges, return node id."""
        nid = _meta_id(stmt) or gen_id(stmt.func_name)
        pos = _meta_pos(stmt)
        d_in = []
        for i, inp in enumerate(stmt.inputs):
            pname = f"in_{i}"
            if hasattr(inp, 'name') and hasattr(inp, 'value'):
                pname = inp.name
            d_in.append(KGPort(port=pname))
        d_out = [KGPort(port=str(o)) for o in stmt.outputs if str(o) != "_"]
        node = KGNode(
            id=nid, type=stmt.func_name, name=stmt.func_name,
            data_inputs=d_in, data_outputs=d_out,
            ctrl_inputs=["in"], ctrl_outputs=["out"],
            properties={}, meta={"pos": pos},
        )
        nodes.append(node)
        # Data edges
        for i, inp in enumerate(stmt.inputs):
            var_name = None
            if isinstance(inp, Identifier):
                var_name = inp.name
            elif hasattr(inp, 'value') and isinstance(inp.value, Identifier):
                var_name = inp.value.name
            if var_name and var_name in var_source:
                src_nid, src_port = var_source[var_name]
                edges.append(KGEdge(
                    type="data", from_node=src_nid, from_port=src_port,
                    to_node=nid, to_port=d_in[i].port if i < len(d_in) else f"in_{i}",
                ))
        # Register outputs
        for o in stmt.outputs:
            if str(o) != "_":
                var_source[str(o)] = (nid, str(o))
        return nid

    def ctrl_edge(from_id: str, from_port: str, to_id: str, to_port: str) -> None:
        edges.append(KGEdge(type="control", from_node=from_id, from_port=from_port, to_node=to_id, to_port=to_port))

    def walk(stmts: list[Statement], prev_ctrl: str | None, in_dataflow: bool, ns_label: str | None = None) -> str | None:
        """Walk statements. Returns last ctrl node id."""
        last_ctrl = prev_ctrl
        first_node_in_scope: str | None = None

        for stmt in stmts:
            match stmt:
                case Assignment():
                    nid = _meta_id(stmt) or gen_id("value")
                    pos = _meta_pos(stmt)
                    val = stmt.value.value if isinstance(stmt.value, Literal) else None
                    nodes.append(KGNode(
                        id=nid, type="value", name=stmt.target,
                        data_inputs=[], data_outputs=[KGPort(port="value")],
                        ctrl_inputs=[], ctrl_outputs=[],
                        properties={"value": val}, meta={"pos": pos},
                    ))
                    var_source[stmt.target] = (nid, "value")
                    if first_node_in_scope is None:
                        first_node_in_scope = nid

                case FuncCall():
                    nid = make_func_node(stmt, in_dataflow)
                    if first_node_in_scope is None:
                        first_node_in_scope = nid
                    if not in_dataflow:
                        if last_ctrl:
                            ctrl_edge(last_ctrl, "out", nid, "in")
                        last_ctrl = nid

                case Branch():
                    nid = _meta_id(stmt) or gen_id("branch")
                    pos = _meta_pos(stmt)
                    nodes.append(KGNode(
                        id=nid, type="branch", name="Branch",
                        data_inputs=[KGPort(port="condition", type="bool")],
                        data_outputs=[],
                        ctrl_inputs=["in"], ctrl_outputs=["true", "false"],
                        properties={}, meta={"pos": pos},
                    ))
                    if isinstance(stmt.condition, Identifier) and stmt.condition.name in var_source:
                        src_nid, src_port = var_source[stmt.condition.name]
                        edges.append(KGEdge(type="data", from_node=src_nid, from_port=src_port, to_node=nid, to_port="condition"))
                    if last_ctrl:
                        ctrl_edge(last_ctrl, "out", nid, "in")
                    if first_node_in_scope is None:
                        first_node_in_scope = nid
                    # Walk branch namespaces (look for them in sibling stmts)
                    for s in stmts:
                        if isinstance(s, Namespace):
                            if s.name == stmt.true_label:
                                inner = walk(s.body, None, False, s.name)
                                if ns_first_node.get(s.name):
                                    ctrl_edge(nid, "true", ns_first_node[s.name], "in")
                            elif s.name == stmt.false_label:
                                inner = walk(s.body, None, False, s.name)
                                if ns_first_node.get(s.name):
                                    ctrl_edge(nid, "false", ns_first_node[s.name], "in")
                    # After branch, code continues — keep branch as last_ctrl
                    # so post-branch statements connect from it
                    last_ctrl = nid

                case Switch():
                    nid = _meta_id(stmt) or gen_id("switch")
                    pos = _meta_pos(stmt)
                    cout = [label for _, label in stmt.cases]
                    if stmt.default_label:
                        cout.append(stmt.default_label)
                    nodes.append(KGNode(
                        id=nid, type="switch", name="Switch",
                        data_inputs=[KGPort(port="value")],
                        data_outputs=[],
                        ctrl_inputs=["in"], ctrl_outputs=cout,
                        properties={}, meta={"pos": pos},
                    ))
                    if isinstance(stmt.value, Identifier) and stmt.value.name in var_source:
                        src_nid, src_port = var_source[stmt.value.name]
                        edges.append(KGEdge(type="data", from_node=src_nid, from_port=src_port, to_node=nid, to_port="value"))
                    if last_ctrl:
                        ctrl_edge(last_ctrl, "out", nid, "in")
                    if first_node_in_scope is None:
                        first_node_in_scope = nid
                    # Walk case namespaces
                    for s in stmts:
                        if isinstance(s, Namespace):
                            for _, label in stmt.cases:
                                if s.name == label:
                                    walk(s.body, None, False, s.name)
                                    if ns_first_node.get(s.name):
                                        ctrl_edge(nid, label, ns_first_node[s.name], "in")
                            if stmt.default_label and s.name == stmt.default_label:
                                walk(s.body, None, False, s.name)
                                if ns_first_node.get(s.name):
                                    ctrl_edge(nid, stmt.default_label, ns_first_node[s.name], "in")
                    last_ctrl = nid

                case Parallel():
                    nid = _meta_id(stmt) or gen_id("parallel")
                    pos = _meta_pos(stmt)
                    nodes.append(KGNode(
                        id=nid, type="parallel", name="Parallel",
                        data_inputs=[], data_outputs=[],
                        ctrl_inputs=["in"], ctrl_outputs=stmt.labels,
                        properties={}, meta={"pos": pos},
                    ))
                    if last_ctrl:
                        ctrl_edge(last_ctrl, "out", nid, "in")
                    if first_node_in_scope is None:
                        first_node_in_scope = nid
                    for s in stmts:
                        if isinstance(s, Namespace) and s.name in stmt.labels:
                            walk(s.body, None, False, s.name)
                            if ns_first_node.get(s.name):
                                ctrl_edge(nid, s.name, ns_first_node[s.name], "in")
                    last_ctrl = nid

                case Jump():
                    # Jump = ctrl wire, not a node
                    jump_wires.append((last_ctrl, stmt.target))
                    last_ctrl = None

                case Namespace():
                    if stmt.name not in ns_first_node:
                        ns_last = walk(stmt.body, last_ctrl, in_dataflow, stmt.name)
                        if ns_last:
                            last_ctrl = ns_last

                case DataflowBlock():
                    # @dataflow: block — transparent in ctrl flow.
                    # Walk contents, create nodes, then chain them sequentially
                    # for visualization (they execute in dependency order).
                    df_nodes_before = len(nodes)
                    walk(stmt.body, None, True)
                    df_new = nodes[df_nodes_before:]

                    if df_new:
                        # Entry: last_ctrl → first node
                        if last_ctrl:
                            ctrl_edge(last_ctrl, "out", df_new[0].id, "in")

                        # Chain within block (sequential for visualization)
                        for i in range(len(df_new) - 1):
                            ctrl_edge(df_new[i].id, "out", df_new[i + 1].id, "in")

                        last_ctrl = df_new[-1].id

                case _:
                    pass

        # Record first node for namespace tracking
        if ns_label and first_node_in_scope:
            ns_first_node[ns_label] = first_node_in_scope

        return last_ctrl

    walk(prog.body, None, False)

    # Wire jump targets
    for from_id, target_label in jump_wires:
        target_first = ns_first_node.get(target_label)
        if target_first and from_id:
            ctrl_edge(from_id, "out", target_first, "in")

    return KirGraph(nodes=nodes, edges=edges)


def _meta_id(stmt: Statement) -> str | None:
    """Extract node_id from @meta if present."""
    if hasattr(stmt, "metadata") and stmt.metadata:
        for m in stmt.metadata:
            if "node_id" in m.data:
                return m.data["node_id"]
    return None


def _meta_pos(stmt: Statement) -> list[int]:
    """Extract pos from @meta if present."""
    if hasattr(stmt, "metadata") and stmt.metadata:
        for m in stmt.metadata:
            if "pos" in m.data:
                p = m.data["pos"]
                return list(p) if isinstance(p, (list, tuple)) else [0, 0]
    return [0, 0]


def print_graph(graph: KirGraph, title: str = "") -> None:
    """Print a human-readable ASCII representation of the graph."""
    if title:
        print(f"{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

    # Nodes
    print(f"\n  NODES ({len(graph.nodes)}):")
    for n in graph.nodes:
        pos = n.meta.get("pos", [0, 0])
        din = [p.port for p in n.data_inputs]
        dout = [p.port for p in n.data_outputs]
        cin = n.ctrl_inputs
        cout = n.ctrl_outputs
        parts = [f"    [{n.id}] type={n.type}"]
        if din:
            parts.append(f"data_in={din}")
        if dout:
            parts.append(f"data_out={dout}")
        if cin:
            parts.append(f"ctrl_in={cin}")
        if cout:
            parts.append(f"ctrl_out={cout}")
        parts.append(f"pos=({pos[0]},{pos[1]})")
        print("  ".join(parts))

    # Edges
    ctrl_edges = [e for e in graph.edges if e.type == "control"]
    data_edges = [e for e in graph.edges if e.type == "data"]

    print(f"\n  CONTROL EDGES ({len(ctrl_edges)}):")
    for e in ctrl_edges:
        print(f"    {e.from_node}.{e.from_port} ──ctrl──> {e.to_node}.{e.to_port}")

    print(f"\n  DATA EDGES ({len(data_edges)}):")
    for e in data_edges:
        print(f"    {e.from_node}.{e.from_port} ──data──> {e.to_node}.{e.to_port}")


def print_ascii_layout(graph: KirGraph) -> None:
    """Print an ASCII grid layout of the graph."""
    if not graph.nodes:
        print("  (empty graph)")
        return

    # Build grid from positions
    nodes_by_pos: dict[tuple[int, int], list[str]] = {}
    pos_map = {}
    for n in graph.nodes:
        p = tuple(n.meta.get("pos", [0, 0]))
        pos_map[n.id] = p

    # Quantize positions to grid cells
    xs = sorted(set(pos_map[n.id][0] for n in graph.nodes))
    ys = sorted(set(pos_map[n.id][1] for n in graph.nodes))

    col_map = {x: i for i, x in enumerate(xs)}
    row_map = {y: i for i, y in enumerate(ys)}

    grid: dict[tuple[int, int], list] = {}
    for n in graph.nodes:
        px, py = pos_map[n.id]
        c, r = col_map[px], row_map[py]
        if (c, r) not in grid:
            grid[(c, r)] = []
        grid[(c, r)].append(n)

    max_col = max(c for c, r in grid) if grid else 0
    max_row = max(r for c, r in grid) if grid else 0

    # Print grid
    print(f"\n  GRID LAYOUT ({max_col + 1} cols x {max_row + 1} rows):")
    print()

    # Column headers
    col_width = 20
    header = "      "
    for c in range(max_col + 1):
        header += f"{'col ' + str(c):^{col_width}}"
    print(header)
    print("      " + "-" * (col_width * (max_col + 1)))

    for r in range(max_row + 1):
        line = f"  r{r:2d} |"
        for c in range(max_col + 1):
            cell_nodes = grid.get((c, r), [])
            if cell_nodes:
                names = ",".join(n.id[:12] for n in cell_nodes)
                line += f" {names:^{col_width - 2}} |"
            else:
                line += f" {'·':^{col_width - 2}} |"
        print(line)

    print("      " + "-" * (col_width * (max_col + 1)))


def print_edge_analysis(graph: KirGraph) -> None:
    """Analyze and print edge quality."""
    score = score_layout(graph)
    print(f"\n  LAYOUT SCORE: {score.total:.1f} (lower = better)")
    print(f"    avg edge cost: {score.avg_edge_cost:.2f}")
    print(f"    max edge cost: {score.max_edge_cost:.1f}")

    if score.edge_scores:
        print(f"\n  WORST EDGES:")
        sorted_edges = sorted(score.edge_scores, key=lambda es: es.cost, reverse=True)
        for es in sorted_edges[:5]:
            print(f"    cost={es.cost:.1f}  {es.edge.from_node}.{es.edge.from_port} -> {es.edge.to_node}.{es.edge.to_port} ({es.edge.type})")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m kohakunode.layout.ascii_view <file.kir|file.kirgraph>")
        sys.exit(1)

    path = Path(sys.argv[1])
    content = path.read_text(encoding="utf-8")

    if path.suffix == ".kirgraph":
        import json

        graph = KirGraph.from_json(content)
    else:
        graph = kir_to_graph(content)

    print_graph(graph, f"Parsed: {path.name}")

    # Auto-layout if needed
    needs_layout = any(
        n.meta.get("pos", [0, 0]) == [0, 0] or "pos" not in n.meta
        for n in graph.nodes
    )
    if needs_layout:
        print("\n  [auto-layout applied]")
        graph = auto_layout(graph)

    print_ascii_layout(graph)
    print_edge_analysis(graph)


if __name__ == "__main__":
    main()
