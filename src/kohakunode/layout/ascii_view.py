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
    KeywordArg,
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
    # jump targets: (from_ctrl_id, from_port, target_label)
    jump_wires: list[tuple[str | None, str, str]] = []
    # Deferred ctrl edges: (from_nid, from_port) awaiting next node
    deferred_ctrl_out: list[tuple[str, str]] = []
    # Track namespaces already walked by Branch/Switch handlers
    walked_ns: set[str] = set()

    def make_func_node(stmt: FuncCall, in_dataflow: bool) -> str:
        """Create a FuncCall node, wire data edges, return node id."""
        nid = _meta_id(stmt) or gen_id(stmt.func_name)
        pos = _meta_pos(stmt)
        d_in = []
        for i, inp in enumerate(stmt.inputs):
            pname = f"in_{i}"
            default = None
            if isinstance(inp, KeywordArg):
                pname = inp.name
                if isinstance(inp.value, Literal):
                    default = inp.value.value
            elif isinstance(inp, Literal):
                default = inp.value
            d_in.append(KGPort(port=pname, default=default))
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

    def wire_deferred(to_nid: str) -> None:
        """Wire all deferred ctrl edges to a target node."""
        for f_nid, f_port in deferred_ctrl_out:
            ctrl_edge(f_nid, f_port, to_nid, "in")
        deferred_ctrl_out.clear()

    def walk(stmts: list[Statement], prev_ctrl: str | None, in_dataflow: bool,
             ns_label: str | None = None, ctrl_out_port: str = "out") -> str | None:
        """Walk statements. Returns last ctrl node id.

        ctrl_out_port: port name to use for the first ctrl edge FROM prev_ctrl.
        This lets Branch pass "true"/"false" so edges use the correct port name.
        """
        last_ctrl = prev_ctrl
        first_node_in_scope: str | None = None
        used_initial_port = False  # Track if we've used ctrl_out_port

        def get_from_port() -> str:
            """Get the correct from_port for a ctrl edge from last_ctrl."""
            nonlocal used_initial_port
            if not used_initial_port and last_ctrl == prev_ctrl:
                used_initial_port = True
                return ctrl_out_port
            return "out"

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
                            ctrl_edge(last_ctrl, get_from_port(), nid, "in")
                        wire_deferred(nid)
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
                        ctrl_edge(last_ctrl, get_from_port(), nid, "in")
                    wire_deferred(nid)
                    if first_node_in_scope is None:
                        first_node_in_scope = nid

                    # Walk branch namespaces with correct port names
                    for s in stmts:
                        if isinstance(s, Namespace):
                            if s.name == stmt.true_label:
                                walked_ns.add(s.name)
                                walk(s.body, nid, False, s.name, ctrl_out_port="true")
                                # Empty namespace → defer edge to next node
                                if not s.body:
                                    deferred_ctrl_out.append((nid, "true"))
                            elif s.name == stmt.false_label:
                                walked_ns.add(s.name)
                                walk(s.body, nid, False, s.name, ctrl_out_port="false")
                                if not s.body:
                                    deferred_ctrl_out.append((nid, "false"))

                    # Branch has no generic "out" — continuation from deferred edges
                    last_ctrl = None

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
                        ctrl_edge(last_ctrl, get_from_port(), nid, "in")
                    wire_deferred(nid)
                    if first_node_in_scope is None:
                        first_node_in_scope = nid

                    # Walk case namespaces with correct port names
                    for s in stmts:
                        if isinstance(s, Namespace):
                            for _, label in stmt.cases:
                                if s.name == label:
                                    walked_ns.add(s.name)
                                    walk(s.body, nid, False, s.name, ctrl_out_port=label)
                                    if not s.body:
                                        deferred_ctrl_out.append((nid, label))
                            if stmt.default_label and s.name == stmt.default_label:
                                walked_ns.add(s.name)
                                walk(s.body, nid, False, s.name, ctrl_out_port=stmt.default_label)
                                if not s.body:
                                    deferred_ctrl_out.append((nid, stmt.default_label))

                    last_ctrl = None

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
                        ctrl_edge(last_ctrl, get_from_port(), nid, "in")
                    wire_deferred(nid)
                    if first_node_in_scope is None:
                        first_node_in_scope = nid
                    for s in stmts:
                        if isinstance(s, Namespace) and s.name in stmt.labels:
                            walked_ns.add(s.name)
                            walk(s.body, nid, False, s.name, ctrl_out_port=s.name)
                    last_ctrl = nid

                case Jump():
                    # Jump = ctrl wire, not a node
                    port = get_from_port()
                    jump_wires.append((last_ctrl, port, stmt.target))
                    last_ctrl = None

                case Namespace():
                    if stmt.name not in ns_first_node and stmt.name not in walked_ns:
                        walked_ns.add(stmt.name)
                        ns_last = walk(stmt.body, last_ctrl, in_dataflow, stmt.name)
                        if ns_last:
                            last_ctrl = ns_last

                case DataflowBlock():
                    # @dataflow: block — NO internal ctrl edges,
                    # but boundary ctrl edges for entry/exit.
                    df_nodes_before = len(nodes)
                    walk(stmt.body, None, True)
                    df_new = nodes[df_nodes_before:]

                    if df_new:
                        first_df = df_new[0].id
                        last_df = df_new[-1].id

                        # Entry boundary: last_ctrl → first node
                        if last_ctrl:
                            ctrl_edge(last_ctrl, get_from_port(), first_df, "in")
                        # Wire deferred edges to first node too
                        wire_deferred(first_df)

                        # Exit boundary: continue ctrl chain from last node
                        last_ctrl = last_df
                        if first_node_in_scope is None:
                            first_node_in_scope = first_df

                case _:
                    pass

        # Record first node for namespace tracking
        if ns_label and first_node_in_scope:
            ns_first_node[ns_label] = first_node_in_scope

        return last_ctrl

    walk(prog.body, None, False)

    # Wire jump targets
    for from_id, from_port, target_label in jump_wires:
        target_first = ns_first_node.get(target_label)
        if target_first and from_id:
            ctrl_edge(from_id, from_port, target_first, "in")

    # Synthesize merge nodes where 2+ ctrl edges converge on one node
    incoming_ctrl: dict[str, list[int]] = {}
    for i, e in enumerate(edges):
        if e.type == "control":
            incoming_ctrl.setdefault(e.to_node, []).append(i)

    for target_nid, edge_indices in incoming_ctrl.items():
        if len(edge_indices) < 2:
            continue
        merge_nid = gen_id("merge")
        n_inputs = len(edge_indices)
        merge_inputs = [f"in_{i}" for i in range(n_inputs)]
        nodes.append(KGNode(
            id=merge_nid, type="merge", name="Merge",
            data_inputs=[], data_outputs=[],
            ctrl_inputs=merge_inputs, ctrl_outputs=["out"],
            properties={}, meta={"pos": [0, 0]},
        ))
        # Rewire: source → merge instead of source → target
        for i, ei in enumerate(edge_indices):
            old = edges[ei]
            edges[ei] = KGEdge(
                type="control", from_node=old.from_node, from_port=old.from_port,
                to_node=merge_nid, to_port=merge_inputs[i],
            )
        # Add merge → target edge
        edges.append(KGEdge(
            type="control", from_node=merge_nid, from_port="out",
            to_node=target_nid, to_port="in",
        ))

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
