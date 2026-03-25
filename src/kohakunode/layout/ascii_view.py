"""ASCII graph viewer for KIR programs.

Parses a .kir file, extracts nodes + edges, and prints a human-readable
text representation showing the graph structure.

Usage:
    python -m kohakunode.layout.ascii_view examples/kir_basics/mixed_mode.kir
"""

import json
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


# ---------------------------------------------------------------------------
# Graph builder — converts KIR AST to KirGraph
# ---------------------------------------------------------------------------


class _GraphBuilder:
    """Stateful walker that converts a KIR AST into a KirGraph.

    Unlike the decompiler (which relies on {node_id}_{port} variable naming),
    this builds the graph by tracking ALL variable definitions and usages,
    handling plain variable names like 'counter', 'total' etc.
    """

    def __init__(self) -> None:
        self.nodes: list[KGNode] = []
        self.edges: list[KGEdge] = []
        self._node_counter = 0
        # var_name -> (node_id, port_name)
        self._var_source: dict[str, tuple[str, str]] = {}
        # namespace_label -> first node id inside that namespace
        self._ns_first_node: dict[str, str | None] = {}
        # jump targets: (from_ctrl_id, from_port, target_label)
        self._jump_wires: list[tuple[str | None, str, str]] = []
        # Deferred ctrl edges: (from_nid, from_port) awaiting next node
        self._deferred_ctrl_out: list[tuple[str, str]] = []
        # Track namespaces already walked by Branch/Switch handlers
        self._walked_ns: set[str] = set()

    def build(self, stmts: list[Statement]) -> KirGraph:
        self._walk(stmts, prev_ctrl=None, in_dataflow=False)
        self._resolve_jump_wires()
        _synthesize_merge_nodes(self.nodes, self.edges)
        return KirGraph(nodes=self.nodes, edges=self.edges)

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    def _gen_id(self, prefix: str) -> str:
        self._node_counter += 1
        return f"{prefix}_{self._node_counter}"

    # ------------------------------------------------------------------
    # Edge helpers
    # ------------------------------------------------------------------

    def _ctrl_edge(
        self, from_id: str, from_port: str, to_id: str, to_port: str
    ) -> None:
        self.edges.append(
            KGEdge(
                type="control",
                from_node=from_id,
                from_port=from_port,
                to_node=to_id,
                to_port=to_port,
            )
        )

    def _wire_deferred(self, to_nid: str) -> None:
        """Wire all pending deferred ctrl edges to the given target node."""
        for f_nid, f_port in self._deferred_ctrl_out:
            self._ctrl_edge(f_nid, f_port, to_nid, "in")
        self._deferred_ctrl_out.clear()

    # ------------------------------------------------------------------
    # Data edge helpers
    # ------------------------------------------------------------------

    def _wire_data_inputs(self, stmt: FuncCall, nid: str, d_in: list[KGPort]) -> None:
        for i, inp in enumerate(stmt.inputs):
            var_name = None
            if isinstance(inp, Identifier):
                var_name = inp.name
            elif hasattr(inp, "value") and isinstance(inp.value, Identifier):
                var_name = inp.value.name
            if var_name and var_name in self._var_source:
                src_nid, src_port = self._var_source[var_name]
                self.edges.append(
                    KGEdge(
                        type="data",
                        from_node=src_nid,
                        from_port=src_port,
                        to_node=nid,
                        to_port=d_in[i].port if i < len(d_in) else f"in_{i}",
                    )
                )

    def _wire_condition(self, condition: object, nid: str, port: str) -> None:
        if isinstance(condition, Identifier) and condition.name in self._var_source:
            src_nid, src_port = self._var_source[condition.name]
            self.edges.append(
                KGEdge(
                    type="data",
                    from_node=src_nid,
                    from_port=src_port,
                    to_node=nid,
                    to_port=port,
                )
            )

    # ------------------------------------------------------------------
    # Node creation
    # ------------------------------------------------------------------

    def _make_func_node(self, stmt: FuncCall) -> str:
        """Create a FuncCall node, wire data edges, return node id."""
        nid = _meta_id(stmt) or self._gen_id(stmt.func_name)
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
        # Strip {node_id}_ prefix from output port names to keep them clean
        prefix = f"{nid}_"
        d_out = []
        for o in stmt.outputs:
            oname = str(o)
            if oname == "_":
                continue
            port_name = oname[len(prefix):] if oname.startswith(prefix) else oname
            d_out.append(KGPort(port=port_name))
        self.nodes.append(
            KGNode(
                id=nid,
                type=stmt.func_name,
                name=stmt.func_name,
                data_inputs=d_in,
                data_outputs=d_out,
                ctrl_inputs=["in"],
                ctrl_outputs=["out"],
                properties={},
                meta={"pos": pos},
            )
        )
        self._wire_data_inputs(stmt, nid, d_in)
        for o in stmt.outputs:
            oname = str(o)
            if oname != "_":
                port_name = oname[len(prefix):] if oname.startswith(prefix) else oname
                self._var_source[oname] = (nid, port_name)
        return nid

    # ------------------------------------------------------------------
    # Match-case handlers
    # ------------------------------------------------------------------

    def _handle_assignment(
        self,
        stmt: Assignment,
        first_node_in_scope: str | None,
    ) -> str | None:
        # If the RHS is an identifier that we already know the source of,
        # just alias the variable (no new node). This handles feedback
        # initialization like `add_5_counter = value_3_value`.
        if isinstance(stmt.value, Identifier) and stmt.value.name in self._var_source:
            self._var_source[stmt.target] = self._var_source[stmt.value.name]
            return first_node_in_scope

        nid = _meta_id(stmt) or self._gen_id("value")
        pos = _meta_pos(stmt)
        val = stmt.value.value if isinstance(stmt.value, Literal) else None
        self.nodes.append(
            KGNode(
                id=nid,
                type="value",
                name=stmt.target,
                data_inputs=[],
                data_outputs=[KGPort(port="value")],
                ctrl_inputs=[],
                ctrl_outputs=[],
                properties={"value": val},
                meta={"pos": pos},
            )
        )
        self._var_source[stmt.target] = (nid, "value")
        return nid if first_node_in_scope is None else first_node_in_scope

    def _handle_funccall(
        self,
        stmt: FuncCall,
        prev_ctrl: str | None,
        in_dataflow: bool,
        first_node_in_scope: str | None,
        last_ctrl: str | None,
        get_from_port,
    ) -> tuple[str | None, str | None]:
        """Returns (updated first_node_in_scope, updated last_ctrl)."""
        nid = self._make_func_node(stmt)
        if first_node_in_scope is None:
            first_node_in_scope = nid
        if not in_dataflow:
            if last_ctrl:
                self._ctrl_edge(last_ctrl, get_from_port(), nid, "in")
            self._wire_deferred(nid)
            last_ctrl = nid
        return first_node_in_scope, last_ctrl

    def _handle_branch(
        self,
        stmt: Branch,
        stmts: list[Statement],
        first_node_in_scope: str | None,
        last_ctrl: str | None,
        get_from_port,
    ) -> tuple[str | None, str | None]:
        """Returns (updated first_node_in_scope, updated last_ctrl=None)."""
        nid = _meta_id(stmt) or self._gen_id("branch")
        pos = _meta_pos(stmt)
        self.nodes.append(
            KGNode(
                id=nid,
                type="branch",
                name="Branch",
                data_inputs=[KGPort(port="condition", type="bool")],
                data_outputs=[],
                ctrl_inputs=["in"],
                ctrl_outputs=["true", "false"],
                properties={},
                meta={"pos": pos},
            )
        )
        self._wire_condition(stmt.condition, nid, "condition")
        if last_ctrl:
            self._ctrl_edge(last_ctrl, get_from_port(), nid, "in")
        self._wire_deferred(nid)
        if first_node_in_scope is None:
            first_node_in_scope = nid

        for s in stmts:
            if not isinstance(s, Namespace):
                continue
            if s.name == stmt.true_label:
                self._walked_ns.add(s.name)
                self._walk(s.body, nid, False, s.name, ctrl_out_port="true")
                if not s.body:
                    self._deferred_ctrl_out.append((nid, "true"))
            elif s.name == stmt.false_label:
                self._walked_ns.add(s.name)
                self._walk(s.body, nid, False, s.name, ctrl_out_port="false")
                if not s.body:
                    self._deferred_ctrl_out.append((nid, "false"))

        return first_node_in_scope, None

    def _handle_switch(
        self,
        stmt: Switch,
        stmts: list[Statement],
        first_node_in_scope: str | None,
        last_ctrl: str | None,
        get_from_port,
    ) -> tuple[str | None, str | None]:
        """Returns (updated first_node_in_scope, updated last_ctrl=None)."""
        nid = _meta_id(stmt) or self._gen_id("switch")
        pos = _meta_pos(stmt)
        cout = [label for _, label in stmt.cases]
        # Store case value→label mapping so compiler can reconstruct switch syntax
        case_map = {}
        for case_expr, label in stmt.cases:
            if isinstance(case_expr, Literal):
                case_map[label] = case_expr.value
            else:
                case_map[label] = str(case_expr)
        if stmt.default_label:
            cout.append(stmt.default_label)
            case_map[stmt.default_label] = "_default_"
        self.nodes.append(
            KGNode(
                id=nid,
                type="switch",
                name="Switch",
                data_inputs=[KGPort(port="value")],
                data_outputs=[],
                ctrl_inputs=["in"],
                ctrl_outputs=cout,
                properties={"cases": case_map},
                meta={"pos": pos},
            )
        )
        self._wire_condition(stmt.value, nid, "value")
        if last_ctrl:
            self._ctrl_edge(last_ctrl, get_from_port(), nid, "in")
        self._wire_deferred(nid)
        if first_node_in_scope is None:
            first_node_in_scope = nid

        for s in stmts:
            if not isinstance(s, Namespace):
                continue
            for _, label in stmt.cases:
                if s.name == label:
                    self._walked_ns.add(s.name)
                    self._walk(s.body, nid, False, s.name, ctrl_out_port=label)
                    if not s.body:
                        self._deferred_ctrl_out.append((nid, label))
            if stmt.default_label and s.name == stmt.default_label:
                self._walked_ns.add(s.name)
                self._walk(s.body, nid, False, s.name, ctrl_out_port=stmt.default_label)
                if not s.body:
                    self._deferred_ctrl_out.append((nid, stmt.default_label))

        return first_node_in_scope, None

    def _handle_parallel(
        self,
        stmt: Parallel,
        stmts: list[Statement],
        first_node_in_scope: str | None,
        last_ctrl: str | None,
        get_from_port,
    ) -> tuple[str | None, str | None]:
        """Returns (updated first_node_in_scope, updated last_ctrl=nid)."""
        nid = _meta_id(stmt) or self._gen_id("parallel")
        pos = _meta_pos(stmt)
        self.nodes.append(
            KGNode(
                id=nid,
                type="parallel",
                name="Parallel",
                data_inputs=[],
                data_outputs=[],
                ctrl_inputs=["in"],
                ctrl_outputs=stmt.labels,
                properties={},
                meta={"pos": pos},
            )
        )
        if last_ctrl:
            self._ctrl_edge(last_ctrl, get_from_port(), nid, "in")
        self._wire_deferred(nid)
        if first_node_in_scope is None:
            first_node_in_scope = nid
        for s in stmts:
            if isinstance(s, Namespace) and s.name in stmt.labels:
                self._walked_ns.add(s.name)
                self._walk(s.body, nid, False, s.name, ctrl_out_port=s.name)
        return first_node_in_scope, nid

    def _handle_dataflow_block(
        self,
        stmt: DataflowBlock,
        first_node_in_scope: str | None,
        last_ctrl: str | None,
        get_from_port,
    ) -> tuple[str | None, str | None]:
        """Returns (updated first_node_in_scope, updated last_ctrl)."""
        df_nodes_before = len(self.nodes)
        df_edges_before = len(self.edges)
        self._walk(stmt.body, None, True)
        df_new = self.nodes[df_nodes_before:]
        df_new_edges = self.edges[df_edges_before:]

        if not df_new:
            return first_node_in_scope, last_ctrl

        first_df = df_new[0].id
        last_df = df_new[-1].id

        # Entry boundary: last_ctrl → first node in block
        if last_ctrl:
            self._ctrl_edge(last_ctrl, get_from_port(), first_df, "in")
        self._wire_deferred(first_df)

        # Chain ALL nodes in lexical order with ctrl pass-through edges.
        # This ensures the compiler keeps every node in the correct scope.
        # Without this, data-only nodes float and get placed by data deps
        # which may pull them into the wrong scope (e.g., into a loop body).
        for i in range(len(df_new) - 1):
            self._ctrl_edge(df_new[i].id, "out", df_new[i + 1].id, "in")

        if first_node_in_scope is None:
            first_node_in_scope = first_df
        return first_node_in_scope, last_df

    # ------------------------------------------------------------------
    # Main walker
    # ------------------------------------------------------------------

    def _walk(
        self,
        stmts: list[Statement],
        prev_ctrl: str | None,
        in_dataflow: bool,
        ns_label: str | None = None,
        ctrl_out_port: str = "out",
    ) -> str | None:
        """Walk statements. Returns last ctrl node id.

        ctrl_out_port: port name to use for the first ctrl edge FROM prev_ctrl.
        This lets Branch pass "true"/"false" so edges use the correct port name.
        """
        last_ctrl = prev_ctrl
        first_node_in_scope: str | None = None
        used_initial_port = False

        def get_from_port() -> str:
            nonlocal used_initial_port
            if not used_initial_port and last_ctrl == prev_ctrl:
                used_initial_port = True
                return ctrl_out_port
            return "out"

        for stmt in stmts:
            match stmt:
                case Assignment():
                    first_node_in_scope = self._handle_assignment(
                        stmt, first_node_in_scope
                    )

                case FuncCall():
                    first_node_in_scope, last_ctrl = self._handle_funccall(
                        stmt,
                        prev_ctrl,
                        in_dataflow,
                        first_node_in_scope,
                        last_ctrl,
                        get_from_port,
                    )

                case Branch():
                    first_node_in_scope, last_ctrl = self._handle_branch(
                        stmt, stmts, first_node_in_scope, last_ctrl, get_from_port
                    )

                case Switch():
                    first_node_in_scope, last_ctrl = self._handle_switch(
                        stmt, stmts, first_node_in_scope, last_ctrl, get_from_port
                    )

                case Parallel():
                    first_node_in_scope, last_ctrl = self._handle_parallel(
                        stmt, stmts, first_node_in_scope, last_ctrl, get_from_port
                    )

                case Jump():
                    port = get_from_port()
                    self._jump_wires.append((last_ctrl, port, stmt.target))
                    last_ctrl = None

                case Namespace():
                    if (
                        stmt.name not in self._ns_first_node
                        and stmt.name not in self._walked_ns
                    ):
                        self._walked_ns.add(stmt.name)
                        ns_last = self._walk(
                            stmt.body, last_ctrl, in_dataflow, stmt.name
                        )
                        if ns_last:
                            last_ctrl = ns_last

                case DataflowBlock():
                    first_node_in_scope, last_ctrl = self._handle_dataflow_block(
                        stmt, first_node_in_scope, last_ctrl, get_from_port
                    )

                case _:
                    pass

        if ns_label and first_node_in_scope:
            self._ns_first_node[ns_label] = first_node_in_scope

        return last_ctrl

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _resolve_jump_wires(self) -> None:
        for from_id, from_port, target_label in self._jump_wires:
            target_first = self._ns_first_node.get(target_label)
            if not target_first:
                continue
            if from_id:
                self._ctrl_edge(from_id, from_port, target_first, "in")
            else:
                # Jump from nowhere (initial loop entry with no preceding ctrl).
                # Create a synthetic entry node so merge synthesis detects the
                # convergence (initial entry + back-edge → 2 incoming ctrl).
                entry_id = self._gen_id("entry")
                self.nodes.append(
                    KGNode(
                        id=entry_id,
                        type="value",
                        name="_entry",
                        data_inputs=[],
                        data_outputs=[],
                        ctrl_inputs=[],
                        ctrl_outputs=["out"],
                        properties={},
                        meta={"pos": [0, 0]},
                    )
                )
                self._ctrl_edge(entry_id, "out", target_first, "in")


def _synthesize_merge_nodes(nodes: list[KGNode], edges: list[KGEdge]) -> None:
    """Insert synthetic Merge nodes wherever 2+ ctrl edges converge on one node."""
    node_counter = [0]

    def gen_id() -> str:
        node_counter[0] += 1
        return f"merge_{node_counter[0]}"

    incoming_ctrl: dict[str, list[int]] = {}
    for i, e in enumerate(edges):
        if e.type == "control":
            incoming_ctrl.setdefault(e.to_node, []).append(i)

    for target_nid, edge_indices in incoming_ctrl.items():
        if len(edge_indices) < 2:
            continue
        merge_nid = gen_id()
        n_inputs = len(edge_indices)
        merge_inputs = [f"in_{i}" for i in range(n_inputs)]
        nodes.append(
            KGNode(
                id=merge_nid,
                type="merge",
                name="Merge",
                data_inputs=[],
                data_outputs=[],
                ctrl_inputs=merge_inputs,
                ctrl_outputs=["out"],
                properties={},
                meta={"pos": [0, 0]},
            )
        )
        for i, ei in enumerate(edge_indices):
            old = edges[ei]
            edges[ei] = KGEdge(
                type="control",
                from_node=old.from_node,
                from_port=old.from_port,
                to_node=merge_nid,
                to_port=merge_inputs[i],
            )
        edges.append(
            KGEdge(
                type="control",
                from_node=merge_nid,
                from_port="out",
                to_node=target_nid,
                to_port="in",
            )
        )


def kir_to_graph(source: str) -> KirGraph:
    """Parse KIR source and extract nodes + edges directly from the AST."""
    prog = parse(source)
    return _GraphBuilder().build(prog.body)


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------


def print_graph(graph: KirGraph, title: str = "") -> None:
    """Print a human-readable ASCII representation of the graph."""
    if title:
        print(f"{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

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

    ctrl_edges = [e for e in graph.edges if e.type == "control"]
    data_edges = [e for e in graph.edges if e.type == "data"]

    print(f"\n  CONTROL EDGES ({len(ctrl_edges)}):")
    for e in ctrl_edges:
        print(f"    {e.from_node}.{e.from_port} ──ctrl──> {e.to_node}.{e.to_port}")

    print(f"\n  DATA EDGES ({len(data_edges)}):")
    for e in data_edges:
        print(f"    {e.from_node}.{e.from_port} ──data──> {e.to_node}.{e.to_port}")


def _build_grid(graph: KirGraph) -> tuple[dict, int, int]:
    """Quantize node positions to grid cells. Returns (grid, max_col, max_row)."""
    pos_map = {n.id: tuple(n.meta.get("pos", [0, 0])) for n in graph.nodes}
    xs = sorted(set(p[0] for p in pos_map.values()))
    ys = sorted(set(p[1] for p in pos_map.values()))
    col_map = {x: i for i, x in enumerate(xs)}
    row_map = {y: i for i, y in enumerate(ys)}

    grid: dict[tuple[int, int], list] = {}
    for n in graph.nodes:
        px, py = pos_map[n.id]
        c, r = col_map[px], row_map[py]
        grid.setdefault((c, r), []).append(n)

    max_col = max(c for c, r in grid) if grid else 0
    max_row = max(r for c, r in grid) if grid else 0
    return grid, max_col, max_row


def print_ascii_layout(graph: KirGraph) -> None:
    """Print an ASCII grid layout of the graph."""
    if not graph.nodes:
        print("  (empty graph)")
        return

    grid, max_col, max_row = _build_grid(graph)

    print(f"\n  GRID LAYOUT ({max_col + 1} cols x {max_row + 1} rows):")
    print()

    cell_w = 18  # inner content width (between | delimiters)
    n_cols = max_col + 1
    # Each column takes: "| " + content(cell_w) + " " = cell_w + 3, plus final "|"
    col_total = cell_w + 3
    rule_width = col_total * n_cols + 1  # +1 for trailing |

    # Header
    header = "      "
    for c in range(n_cols):
        label = f"col {c}"
        header += f"| {label:^{cell_w}} "
    header += "|"
    print(header)
    print("      " + "-" * rule_width)

    for r in range(max_row + 1):
        line = f"  r{r:2d} "
        for c in range(n_cols):
            cell_nodes = grid.get((c, r), [])
            if cell_nodes:
                names = ",".join(n.id[:cell_w] for n in cell_nodes)
                line += f"| {names:^{cell_w}} "
            else:
                line += f"| {'·':^{cell_w}} "
        line += "|"
        print(line)

    print("      " + "-" * rule_width)


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
            print(
                f"    cost={es.cost:.1f}  {es.edge.from_node}.{es.edge.from_port} -> {es.edge.to_node}.{es.edge.to_port} ({es.edge.type})"
            )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m kohakunode.layout.ascii_view <file.kir|file.kirgraph>")
        sys.exit(1)

    path = Path(sys.argv[1])
    content = path.read_text(encoding="utf-8")

    if path.suffix == ".kirgraph":
        graph = KirGraph.from_json(content)
    else:
        graph = kir_to_graph(content)

    print_graph(graph, f"Parsed: {path.name}")

    needs_layout = any(
        n.meta.get("pos", [0, 0]) == [0, 0] or "pos" not in n.meta for n in graph.nodes
    )
    if needs_layout:
        print("\n  [auto-layout applied]")
        graph = auto_layout(graph)

    print_ascii_layout(graph)
    print_edge_analysis(graph)


if __name__ == "__main__":
    main()
