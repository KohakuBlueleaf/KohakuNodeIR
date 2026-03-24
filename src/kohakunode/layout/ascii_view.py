"""ASCII graph viewer for KIR programs.

Parses a .kir file, extracts nodes + edges, and prints a human-readable
text representation showing the graph structure.

Usage:
    python -m kohakunode.layout.ascii_view examples/kir_basics/mixed_mode.kir
"""

import sys
from pathlib import Path
from typing import Any

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

    def walk(stmts: list[Statement], prev_ctrl_id: str | None, in_dataflow: bool) -> str | None:
        """Walk statements, create nodes + edges. Returns last ctrl node id."""
        last_ctrl = prev_ctrl_id
        dataflow_node_ids: list[str] = []

        for stmt in stmts:
            match stmt:
                case Assignment():
                    nid = gen_id("value") if not stmt.metadata else _meta_id(stmt) or gen_id("value")
                    pos = _meta_pos(stmt)
                    val = stmt.value.value if isinstance(stmt.value, Literal) else None
                    node = KGNode(
                        id=nid, type="value", name=stmt.target,
                        data_inputs=[], data_outputs=[KGPort(port="value")],
                        ctrl_inputs=[], ctrl_outputs=[],
                        properties={"value": val}, meta={"pos": pos},
                    )
                    nodes.append(node)
                    var_source[stmt.target] = (nid, "value")
                    if in_dataflow:
                        dataflow_node_ids.append(nid)

                case FuncCall():
                    nid = _meta_id(stmt) or gen_id(stmt.func_name)
                    pos = _meta_pos(stmt)
                    # Data inputs
                    d_in = []
                    for i, inp in enumerate(stmt.inputs):
                        port_name = inp.name if isinstance(inp, type(inp)) and hasattr(inp, 'name') and hasattr(inp, 'value') else f"in_{i}"
                        if hasattr(inp, 'name') and hasattr(inp, 'value'):
                            # KeywordArg
                            port_name = inp.name
                        d_in.append(KGPort(port=port_name if port_name != f"in_{i}" else f"in_{i}"))
                    # Data outputs
                    d_out = [KGPort(port=str(o)) for o in stmt.outputs if str(o) != "_"]
                    node = KGNode(
                        id=nid, type=stmt.func_name, name=stmt.func_name,
                        data_inputs=d_in, data_outputs=d_out,
                        ctrl_inputs=["in"], ctrl_outputs=["out"],
                        properties={}, meta={"pos": pos},
                    )
                    nodes.append(node)

                    # Data edges from inputs
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

                    # Control edges
                    if not in_dataflow:
                        if last_ctrl:
                            edges.append(KGEdge(
                                type="control", from_node=last_ctrl, from_port="out",
                                to_node=nid, to_port="in",
                            ))
                        last_ctrl = nid
                    else:
                        dataflow_node_ids.append(nid)

                case Branch():
                    nid = _meta_id(stmt) or gen_id("branch")
                    pos = _meta_pos(stmt)
                    node = KGNode(
                        id=nid, type="branch", name="Branch",
                        data_inputs=[KGPort(port="condition", type="bool")],
                        data_outputs=[],
                        ctrl_inputs=["in"], ctrl_outputs=["true", "false"],
                        properties={}, meta={"pos": pos},
                    )
                    nodes.append(node)
                    # Data edge for condition
                    if isinstance(stmt.condition, Identifier) and stmt.condition.name in var_source:
                        src_nid, src_port = var_source[stmt.condition.name]
                        edges.append(KGEdge(type="data", from_node=src_nid, from_port=src_port, to_node=nid, to_port="condition"))
                    if last_ctrl:
                        edges.append(KGEdge(type="control", from_node=last_ctrl, from_port="out", to_node=nid, to_port="in"))
                    last_ctrl = None  # branches split

                case Jump():
                    # Jump is a wire, not a node — store for later
                    pass  # handled by namespace walk

                case Namespace():
                    # Walk namespace body
                    inner_last = walk(stmt.body, last_ctrl, in_dataflow)
                    last_ctrl = None  # namespace doesn't chain to next

                case DataflowBlock():
                    # Walk dataflow body — ctrl from prev connects to roots, leaves connect to next
                    inner_last = walk(stmt.body, None, True)
                    # After dataflow block, ctrl continues
                    # (simplified: just continue from last_ctrl)

                case _:
                    pass

        return last_ctrl

    walk(prog.body, None, False)
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
