"""L1 -> L2 compiler: KirGraph (.kirgraph) -> KIR Program AST."""

from collections import defaultdict
from typing import Any

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    Expression,
    FuncCall,
    Identifier,
    Jump,
    Literal,
    MetaAnnotation,
    Namespace,
    Parallel,
    Program,
    Statement,
    Switch,
)
from kohakunode.kirgraph.schema import KGNode, KirGraph


def _var(node_id: str, port: str) -> str:
    if port.startswith(f"{node_id}_"):
        return port
    return f"{node_id}_{port}"


def _lit(value: Any) -> Literal:
    if value is None:
        return Literal(value=None, literal_type="none")
    if isinstance(value, bool):
        return Literal(value=value, literal_type="bool")
    if isinstance(value, int):
        return Literal(value=value, literal_type="int")
    if isinstance(value, float):
        return Literal(value=value, literal_type="float")
    return Literal(value=str(value), literal_type="str")


def _meta(node: KGNode) -> MetaAnnotation:
    data: dict[str, Any] = {"node_id": node.id}
    if "pos" in node.meta:
        p = node.meta["pos"]
        data["pos"] = tuple(p) if isinstance(p, list) else p
    for k, v in node.meta.items():
        if k != "pos":
            data[k] = v
    return MetaAnnotation(data=data)


class KirGraphCompiler:
    """Compile .kirgraph (L1) → KIR Program AST (L2)."""

    def compile(self, graph: KirGraph) -> Program:
        self._nodes: dict[str, KGNode] = {n.id: n for n in graph.nodes}

        # Adjacency
        self._ctrl_out: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        self._ctrl_in: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        self._data_in: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        self._ctrl_connected: set[str] = set()

        # Which ctrl_in ports are connected (node_id → set of port names)
        self._connected_ctrl_in_ports: dict[str, set[str]] = defaultdict(set)

        for edge in graph.edges:
            if edge.type == "control":
                self._ctrl_out[edge.from_node].append((edge.from_port, edge.to_node, edge.to_port))
                self._ctrl_in[edge.to_node].append((edge.from_node, edge.from_port, edge.to_port))
                self._ctrl_connected.add(edge.from_node)
                self._ctrl_connected.add(edge.to_node)
                self._connected_ctrl_in_ports[edge.to_node].add(edge.to_port)
            else:
                self._data_in[edge.to_node][edge.to_port] = (edge.from_node, edge.from_port)

        self._visited: set[str] = set()

        # Build loop body info and feedback variable map
        self._build_loop_info()

        # Partition unconnected nodes into:
        # - independent: only depend on other unconnected or external (value nodes)
        # - dependent: depend on at least one ctrl-connected node
        ctrl_nodes = [n for n in graph.nodes if n.id in self._ctrl_connected]
        unconnected = [n for n in graph.nodes if n.id not in self._ctrl_connected]

        independent = []
        self._dependent_nodes: dict[str, KGNode] = {}  # node_id → node

        for n in unconnected:
            if self._depends_on_ctrl(n.id):
                self._dependent_nodes[n.id] = n
            else:
                independent.append(n)

        body: list[Statement] = []
        if independent:
            body.append(DataflowBlock(body=[s for n in independent for s in self._emit_node_raw(n)]))
            for n in independent:
                self._visited.add(n.id)
        if ctrl_nodes:
            body.extend(self._emit_ctrl(ctrl_nodes))
        return Program(body=body)

    def _depends_on_ctrl(self, node_id: str) -> bool:
        """Check if a node (transitively) depends on any ctrl-connected node."""
        visited: set[str] = set()
        stack = [node_id]
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            for port, (src_node, _src_port) in self._data_in.get(nid, {}).items():
                if src_node in self._ctrl_connected:
                    return True
                if src_node not in self._ctrl_connected:
                    stack.append(src_node)
        return False

    # ── Loop body detection ──

    def _build_loop_info(self) -> None:
        """Identify which nodes are inside loop bodies and build feedback map.

        A node is "inside a loop" if it's reachable from a merge node's ctrl output.
        The feedback map maps (node_id, input_port) → output_var_name when the input
        crosses the loop boundary from an initial value to a loop-updating node.
        """
        self._loop_body_nodes: set[str] = set()
        self._feedback_vars: dict[tuple[str, str], str] = {}

        # Find all merge nodes and their loop bodies
        merge_ids = [n.id for n in self._nodes.values() if n.type == "merge"]
        for merge_id in merge_ids:
            # Nodes reachable from merge via ctrl (the loop body)
            body = self._reachable(merge_id)
            body.discard(merge_id)
            self._loop_body_nodes |= body

        if not self._loop_body_nodes:
            return

        # For each node inside a loop, check if its data inputs come from
        # outside the loop (initial values). If the node also outputs a variable,
        # use that output name for the input on subsequent iterations.
        for nid in self._loop_body_nodes:
            node = self._nodes.get(nid)
            if not node or not node.data_outputs:
                continue
            conn = self._data_in.get(nid, {})
            for in_port, (src_node, src_port) in conn.items():
                if src_node not in self._loop_body_nodes and src_node not in merge_ids:
                    # Input crosses loop boundary (from initial value to loop body)
                    # Find the corresponding output port — use index matching
                    in_idx = next(
                        (i for i, p in enumerate(node.data_inputs) if p.port == in_port),
                        -1,
                    )
                    if in_idx >= 0 and in_idx < len(node.data_outputs):
                        out_port = node.data_outputs[in_idx].port
                        self._feedback_vars[(nid, in_port)] = _var(nid, out_port)

    # ── Data input resolution ──

    def _input(self, node: KGNode, port: str) -> Expression:
        # Check if this input should use a feedback variable (loop self-reference)
        fb = self._feedback_vars.get((node.id, port))
        if fb:
            return Identifier(name=fb)

        conn = self._data_in.get(node.id, {})
        if port in conn:
            return Identifier(name=_var(conn[port][0], conn[port][1]))
        for p in node.data_inputs:
            if p.port == port and p.default is not None:
                return _lit(p.default)
        return _lit(0)

    # ── Emit single node ──

    def _emit_node(self, node: KGNode) -> list[Statement]:
        m = _meta(node)
        stmts: list[Statement] = []

        match node.type:
            case "value":
                val = node.properties.get("value", 0)
                out = node.data_outputs[0].port if node.data_outputs else "value"
                stmts.append(Assignment(target=_var(node.id, out), value=_lit(val), metadata=[m]))
            case "merge":
                pass
            case "branch":
                stmts.extend(self._emit_branch(node, m))
            case "switch":
                stmts.extend(self._emit_switch(node, m))
            case "parallel":
                stmts.extend(self._emit_parallel(node, m))
            case _:
                inputs = [self._input(node, p.port) for p in node.data_inputs]
                outputs = [_var(node.id, p.port) for p in node.data_outputs]
                stmts.append(FuncCall(inputs=inputs, func_name=node.type, outputs=outputs, metadata=[m]))

        # After emitting this ctrl node, also emit any dependent non-ctrl nodes
        # whose data inputs are now satisfied.
        stmts.extend(self._emit_ready_dependents(node.id))
        return stmts

    def _emit_ready_dependents(self, just_emitted_id: str) -> list[Statement]:
        """Emit non-ctrl nodes that are now ready, wrapped in @dataflow: block."""
        df_stmts: list[Statement] = []
        emitted_ids: set[str] = set()

        changed = True
        while changed:
            changed = False
            for nid, node in list(self._dependent_nodes.items()):
                if nid in emitted_ids:
                    continue
                if self._all_data_sources_emitted(nid, emitted_ids):
                    emitted_ids.add(nid)
                    del self._dependent_nodes[nid]
                    df_stmts.extend(self._emit_node_raw(node))
                    changed = True

        if not df_stmts:
            return []
        # Wrap in @dataflow: block since these nodes have no control ordering
        return [DataflowBlock(body=df_stmts)]

    def _all_data_sources_emitted(self, node_id: str, extra_emitted: set[str]) -> bool:
        """Check if ALL data sources for a node have been emitted."""
        for _port, (src_node, _src_port) in self._data_in.get(node_id, {}).items():
            if src_node not in self._visited and src_node not in extra_emitted:
                return False
        return True

    def _emit_node_raw(self, node: KGNode) -> list[Statement]:
        """Emit a node without checking dependents (to avoid recursion)."""
        m = _meta(node)
        if node.type == "value":
            val = node.properties.get("value", 0)
            out = node.data_outputs[0].port if node.data_outputs else "value"
            return [Assignment(target=_var(node.id, out), value=_lit(val), metadata=[m])]
        inputs = [self._input(node, p.port) for p in node.data_inputs]
        outputs = [_var(node.id, p.port) for p in node.data_outputs]
        return [FuncCall(inputs=inputs, func_name=node.type, outputs=outputs, metadata=[m])]

    def _emit_branch(self, node: KGNode, m: MetaAnnotation) -> list[Statement]:
        cond = self._input(node, "condition")
        tp = node.ctrl_outputs[0] if len(node.ctrl_outputs) > 0 else "true"
        fp = node.ctrl_outputs[1] if len(node.ctrl_outputs) > 1 else "false"
        tl, fl = f"{node.id}_{tp}", f"{node.id}_{fp}"
        stmts: list[Statement] = [Branch(condition=cond, true_label=tl, false_label=fl, metadata=[m])]
        for port, label in [(tp, tl), (fp, fl)]:
            stmts.append(Namespace(name=label, body=self._chain_from_port(node.id, port)))
        return stmts

    def _emit_switch(self, node: KGNode, m: MetaAnnotation) -> list[Statement]:
        val = self._input(node, "value")
        cp = node.properties.get("cases", {})
        cases, dl, labels = [], None, []
        for port in node.ctrl_outputs:
            label = f"{node.id}_{port}"
            if cp.get(port) == "_default_" or port == "default":
                dl = label
            elif port in cp:
                cases.append((_lit(cp[port]), label))
            else:
                cases.append((_lit(port), label))
            labels.append((port, label))
        stmts: list[Statement] = [Switch(value=val, cases=cases, default_label=dl, metadata=[m])]
        for port, label in labels:
            stmts.append(Namespace(name=label, body=self._chain_from_port(node.id, port)))
        return stmts

    def _emit_parallel(self, node: KGNode, m: MetaAnnotation) -> list[Statement]:
        labels = [f"{node.id}_{p}" for p in node.ctrl_outputs]
        stmts: list[Statement] = [Parallel(labels=labels, metadata=[m])]
        for port, label in zip(node.ctrl_outputs, labels):
            stmts.append(Namespace(name=label, body=self._chain_from_port(node.id, port)))
        return stmts

    # ── Control chain walking ──

    def _emit_ctrl(self, ctrl_nodes: list[KGNode]) -> list[Statement]:
        # Entry = node with ctrl_outputs and either:
        # - no incoming ctrl edges at all, OR
        # - is a merge with unconnected ctrl_in ports (loop entry)
        entry_ids = []
        for n in ctrl_nodes:
            ins = self._ctrl_in.get(n.id, [])
            if not ins:
                entry_ids.append(n.id)
            elif n.type == "merge":
                # Merge with some unconnected ctrl_in ports → entry
                connected_ports = self._connected_ctrl_in_ports.get(n.id, set())
                if len(connected_ports) < len(n.ctrl_inputs):
                    entry_ids.append(n.id)

        if not entry_ids:
            by_pos = sorted(ctrl_nodes, key=lambda n: (n.meta.get("pos", [0, 0])[1], n.meta.get("pos", [0, 0])[0]))
            entry_ids = [by_pos[0].id]

        stmts: list[Statement] = []
        for eid in entry_ids:
            stmts.extend(self._walk(eid))
        return stmts

    def _walk(self, node_id: str) -> list[Statement]:
        stmts: list[Statement] = []
        cur: str | None = node_id

        while cur is not None:
            if cur in self._visited:
                # Backward edge → jump to existing namespace
                stmts.append(Jump(target=f"ns_{cur}"))
                break

            node = self._nodes[cur]

            # Merge node → wrap rest of loop in a namespace
            # Attach merge's @meta to the jump so decompiler can recover position
            if node.type == "merge":
                ns_label = f"ns_{cur}"
                merge_meta = _meta(node)
                self._visited.add(cur)
                next_id = self._next(node)

                # Emit initialization assignments for feedback variables.
                # These bridge the initial value → loop variable before the first iteration.
                for (nid, in_port), fb_var in self._feedback_vars.items():
                    conn = self._data_in.get(nid, {})
                    if in_port in conn:
                        src_node, src_port = conn[in_port]
                        init_var = _var(src_node, src_port)
                        if init_var != fb_var:
                            stmts.append(Assignment(
                                target=fb_var,
                                value=Identifier(name=init_var),
                            ))

                inner = self._walk(next_id) if next_id else []
                stmts.append(Jump(target=ns_label, metadata=[merge_meta]))
                stmts.append(Namespace(name=ns_label, body=inner))
                break

            self._visited.add(cur)
            stmts.extend(self._emit_node(node))

            if node.type in ("branch", "switch", "parallel"):
                merge_id = self._find_merge(node)
                cur = merge_id if merge_id and merge_id not in self._visited else None
            else:
                cur = self._next(node)

        return stmts

    def _chain_from_port(self, node_id: str, port: str) -> list[Statement]:
        for fp, to_id, _tp in self._ctrl_out.get(node_id, []):
            if fp == port:
                return self._walk(to_id)
        return []

    def _next(self, node: KGNode) -> str | None:
        outs = self._ctrl_out.get(node.id, [])
        return outs[0][1] if len(outs) == 1 else None

    def _find_merge(self, node: KGNode) -> str | None:
        outs = self._ctrl_out.get(node.id, [])
        if not outs:
            return None
        sets = [self._reachable(to) for _, to, _ in outs]
        common = sets[0]
        for s in sets[1:]:
            common &= s
        for nid in common:
            if self._nodes[nid].type == "merge":
                return nid
        for nid in common:
            if len(self._ctrl_in.get(nid, [])) >= 2:
                return nid
        return None

    def _reachable(self, start: str) -> set[str]:
        vis: set[str] = set()
        stk = [start]
        while stk:
            n = stk.pop()
            if n in vis:
                continue
            vis.add(n)
            for _, to, _ in self._ctrl_out.get(n, []):
                stk.append(to)
        return vis
