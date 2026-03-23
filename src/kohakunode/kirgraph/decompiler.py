"""L2 -> L1 decompiler: KIR Program AST -> KirGraph (.kirgraph).

Recovers a flat node-and-edge graph from a KIR AST by reading @meta
annotations and inferring topology from variable references and control flow.
"""

from __future__ import annotations

import re
from typing import Any

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    Expression,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    Literal,
    MetaAnnotation,
    Namespace,
    Parallel,
    Program,
    Statement,
    Switch,
)
from kohakunode.kirgraph.schema import KGEdge, KGNode, KGPort, KirGraph

# Pattern to decompose variable names into node_id + port_name.
# Matches the longest prefix that corresponds to a known node id.
_VAR_PATTERN = re.compile(r"^(.+?)_([^_]+)$")


def _extract_meta(stmt: Statement) -> dict[str, Any] | None:
    """Extract @meta data from a statement if it has metadata."""
    metadata: list[MetaAnnotation] | None = None
    if isinstance(stmt, (Assignment, FuncCall, Branch, Switch, Jump, Parallel)):
        metadata = stmt.metadata
    if metadata:
        merged: dict[str, Any] = {}
        for m in metadata:
            merged.update(m.data)
        return merged
    return None


def _extract_identifiers(expr: Expression) -> list[str]:
    """Collect all identifier names from an expression tree."""
    names: list[str] = []
    if isinstance(expr, Identifier):
        names.append(expr.name)
    elif isinstance(expr, KeywordArg):
        names.extend(_extract_identifiers(expr.value))
    return names


def _literal_value(expr: Expression) -> Any:
    """Extract a Python value from a Literal expression."""
    if isinstance(expr, Literal):
        return expr.value
    return None


def _parse_var_name(
    var_name: str, known_node_ids: set[str]
) -> tuple[str, str] | None:
    """Try to split a variable name into (node_id, port_name).

    Tries the longest matching node_id prefix first.
    """
    # Try known node ids first (greedy match).
    for nid in sorted(known_node_ids, key=len, reverse=True):
        prefix = nid + "_"
        if var_name.startswith(prefix) and len(var_name) > len(prefix):
            return (nid, var_name[len(prefix):])

    # Fallback: use regex for the last underscore split.
    m = _VAR_PATTERN.match(var_name)
    if m:
        return (m.group(1), m.group(2))
    return None


class KirGraphDecompiler:
    """Decompile a KIR Program AST (Level 2) back to a KirGraph (Level 1)."""

    def decompile(self, program: Program) -> KirGraph:
        """Convert a KIR AST back to a .kirgraph."""
        self._nodes: dict[str, KGNode] = {}
        self._edges: list[KGEdge] = []
        self._var_to_node_port: dict[str, tuple[str, str]] = {}
        self._node_counter = 0
        self._handled_namespaces: set[str] = set()

        # First pass: collect all nodes and their output variables.
        self._walk_statements(program.body, prev_node_id=None, in_namespace=False)

        # Second pass: resolve data edges from variable references.
        known_ids = set(self._nodes.keys())
        self._resolve_data_edges(program.body, known_ids)

        return KirGraph(
            nodes=list(self._nodes.values()),
            edges=list(self._edges),
        )

    # ------------------------------------------------------------------
    # First pass: node creation + control edges
    # ------------------------------------------------------------------

    def _walk_statements(
        self,
        stmts: list[Statement],
        prev_node_id: str | None,
        in_namespace: bool,
        in_dataflow: bool = False,
        parent_branch_edge: tuple[str, str] | None = None,
    ) -> str | None:
        """Walk statements, creating nodes and control edges.

        Returns the last node_id emitted (for chaining control edges).
        """
        last_id = prev_node_id

        for stmt in stmts:
            if isinstance(stmt, DataflowBlock):
                # Dataflow blocks: nodes with NO ctrl edges
                self._walk_statements(
                    stmt.body, prev_node_id=None, in_namespace=False, in_dataflow=True
                )
                continue

            if isinstance(stmt, Namespace):
                if stmt.name not in self._handled_namespaces:
                    # Walk namespace body — merge node handles the ctrl edge in
                    self._walk_statements(stmt.body, prev_node_id=last_id, in_namespace=True)
                # After a namespace (entered via jump), don't chain to next
                last_id = None
                continue

            if isinstance(stmt, Jump):
                target_ns = stmt.target
                # Extract @meta from the jump (carries merge node position)
                jump_meta = _extract_meta(stmt)
                if target_ns.startswith("ns_"):
                    merge_id = target_ns[3:]
                    if merge_id in self._nodes:
                        # Backward edge (loop back)
                        merge_node = self._nodes[merge_id]
                        back_port = "back" if "back" in merge_node.ctrl_inputs else (
                            merge_node.ctrl_inputs[-1] if merge_node.ctrl_inputs else "back"
                        )
                        if last_id:
                            prev_node = self._nodes[last_id]
                            from_port = prev_node.ctrl_outputs[0] if prev_node.ctrl_outputs else "out"
                            self._edges.append(KGEdge(
                                type="control", from_node=last_id, from_port=from_port,
                                to_node=merge_id, to_port=back_port,
                            ))
                        elif parent_branch_edge:
                            # Inside a branch namespace with no preceding nodes
                            self._edges.append(KGEdge(
                                type="control",
                                from_node=parent_branch_edge[0],
                                from_port=parent_branch_edge[1],
                                to_node=merge_id, to_port=back_port,
                            ))
                    else:
                        # Forward jump — create merge node
                        merge_node = KGNode(
                            id=merge_id, type="merge", name="Merge",
                            data_inputs=[], data_outputs=[],
                            ctrl_inputs=["entry", "back"], ctrl_outputs=["out"],
                            meta=self._build_meta(jump_meta),
                        )
                        self._nodes[merge_id] = merge_node
                        if last_id:
                            prev_node = self._nodes[last_id]
                            from_port = prev_node.ctrl_outputs[0] if prev_node.ctrl_outputs else "out"
                            self._edges.append(KGEdge(
                                type="control", from_node=last_id, from_port=from_port,
                                to_node=merge_id, to_port="entry",
                            ))
                        last_id = merge_id
                continue

            node_id = self._create_node_from_stmt(stmt)
            if node_id is None:
                continue

            # Control edge from previous (skip in dataflow blocks)
            if last_id is not None and not in_dataflow:
                node = self._nodes[node_id]
                prev_node = self._nodes[last_id]
                from_port = prev_node.ctrl_outputs[0] if prev_node.ctrl_outputs else "out"
                to_port = node.ctrl_inputs[0] if node.ctrl_inputs else "in"
                self._edges.append(KGEdge(
                    type="control", from_node=last_id, from_port=from_port,
                    to_node=node_id, to_port=to_port,
                ))

            if in_dataflow:
                pass  # No ctrl chaining in dataflow blocks
            elif isinstance(stmt, Branch):
                self._handle_branch_namespaces(stmt, node_id, stmts)
                last_id = None
            elif isinstance(stmt, Switch):
                self._handle_switch_namespaces(stmt, node_id, stmts)
                last_id = None
            elif isinstance(stmt, Parallel):
                self._handle_parallel_namespaces(stmt, node_id, stmts)
                last_id = None
            else:
                last_id = node_id

        return last_id

    def _create_node_from_stmt(self, stmt: Statement) -> str | None:
        """Create a KGNode from a statement. Returns the node id or None."""
        meta = _extract_meta(stmt)
        node_id = meta.get("node_id") if meta else None

        if isinstance(stmt, Assignment):
            return self._create_value_node(stmt, node_id, meta)
        if isinstance(stmt, FuncCall):
            return self._create_func_node(stmt, node_id, meta)
        if isinstance(stmt, Branch):
            return self._create_branch_node(stmt, node_id, meta)
        if isinstance(stmt, Switch):
            return self._create_switch_node(stmt, node_id, meta)
        if isinstance(stmt, Parallel):
            return self._create_parallel_node(stmt, node_id, meta)
        if isinstance(stmt, Jump):
            # Jump is a control primitive, not a node.
            return None

        return None

    def _create_value_node(
        self,
        stmt: Assignment,
        node_id: str | None,
        meta_data: dict[str, Any] | None,
    ) -> str:
        """Create a value node from an Assignment."""
        if node_id is None:
            # Infer node_id from variable name.
            parts = _parse_var_name(stmt.target, set(self._nodes.keys()))
            if parts:
                node_id = parts[0]
            else:
                node_id = self._gen_id("value")

        # Determine value and type.
        value: Any = None
        value_type = "any"
        if isinstance(stmt.value, Literal):
            value = stmt.value.value
            value_type = stmt.value.literal_type
            if value_type == "none":
                value_type = "any"

        # Determine output port name.
        parts = _parse_var_name(stmt.target, {node_id})
        port_name = parts[1] if parts else "value"

        node = KGNode(
            id=node_id,
            type="value",
            name=f"Value {node_id}",
            data_inputs=[],
            data_outputs=[KGPort(port=port_name, type=value_type)],
            ctrl_inputs=[],
            ctrl_outputs=[],
            properties={"value_type": value_type, "value": value},
            meta=self._build_meta(meta_data),
        )
        self._nodes[node_id] = node
        self._var_to_node_port[stmt.target] = (node_id, port_name)
        return node_id

    def _create_func_node(
        self,
        stmt: FuncCall,
        node_id: str | None,
        meta_data: dict[str, Any] | None,
    ) -> str:
        """Create a function node from a FuncCall."""
        if node_id is None:
            node_id = self._gen_id(stmt.func_name)

        # Build data input ports.
        data_inputs: list[KGPort] = []
        for i, inp in enumerate(stmt.inputs):
            if isinstance(inp, KeywordArg):
                port_name = inp.name
                default = _literal_value(inp.value)
                data_inputs.append(KGPort(port=port_name, default=default))
            elif isinstance(inp, Identifier):
                # Try to infer port name from function convention.
                port_name = self._infer_input_port_name(i, stmt)
                data_inputs.append(KGPort(port=port_name))
            elif isinstance(inp, Literal):
                port_name = self._infer_input_port_name(i, stmt)
                data_inputs.append(
                    KGPort(port=port_name, default=inp.value)
                )
            else:
                port_name = f"in_{i}"
                data_inputs.append(KGPort(port=port_name))

        # Build data output ports.
        data_outputs: list[KGPort] = []
        for out in stmt.outputs:
            if isinstance(out, str):
                parts = _parse_var_name(out, {node_id})
                port_name = parts[1] if parts else out
                data_outputs.append(KGPort(port=port_name))

        node = KGNode(
            id=node_id,
            type=stmt.func_name,
            name=stmt.func_name.replace("_", " ").title(),
            data_inputs=data_inputs,
            data_outputs=data_outputs,
            ctrl_inputs=["in"],
            ctrl_outputs=["out"],
            meta=self._build_meta(meta_data),
        )
        self._nodes[node_id] = node

        # Register output variables.
        for out in stmt.outputs:
            if isinstance(out, str):
                parts = _parse_var_name(out, {node_id})
                port = parts[1] if parts else out
                self._var_to_node_port[out] = (node_id, port)

        return node_id

    def _create_branch_node(
        self,
        stmt: Branch,
        node_id: str | None,
        meta_data: dict[str, Any] | None,
    ) -> str:
        """Create a branch node from a Branch statement."""
        if node_id is None:
            node_id = self._gen_id("branch")

        node = KGNode(
            id=node_id,
            type="branch",
            name="Branch",
            data_inputs=[KGPort(port="condition", type="bool")],
            data_outputs=[],
            ctrl_inputs=["in"],
            ctrl_outputs=["true", "false"],
            meta=self._build_meta(meta_data),
        )
        self._nodes[node_id] = node
        return node_id

    def _create_switch_node(
        self,
        stmt: Switch,
        node_id: str | None,
        meta_data: dict[str, Any] | None,
    ) -> str:
        """Create a switch node from a Switch statement."""
        if node_id is None:
            node_id = self._gen_id("switch")

        ctrl_outputs: list[str] = []
        cases_prop: dict[str, Any] = {}
        for expr, label in stmt.cases:
            # Extract port name from label (node_id_portname pattern).
            parts = _parse_var_name(label, {node_id})
            port = parts[1] if parts else label
            ctrl_outputs.append(port)
            cases_prop[port] = _literal_value(expr)

        if stmt.default_label:
            ctrl_outputs.append("default")

        node = KGNode(
            id=node_id,
            type="switch",
            name="Switch",
            data_inputs=[KGPort(port="value", type="any")],
            data_outputs=[],
            ctrl_inputs=["in"],
            ctrl_outputs=ctrl_outputs,
            properties={"cases": cases_prop} if cases_prop else {},
            meta=self._build_meta(meta_data),
        )
        self._nodes[node_id] = node
        return node_id

    def _create_parallel_node(
        self,
        stmt: Parallel,
        node_id: str | None,
        meta_data: dict[str, Any] | None,
    ) -> str:
        """Create a parallel node from a Parallel statement."""
        if node_id is None:
            node_id = self._gen_id("parallel")

        ctrl_outputs: list[str] = []
        for label in stmt.labels:
            parts = _parse_var_name(label, {node_id})
            port = parts[1] if parts else label
            ctrl_outputs.append(port)

        node = KGNode(
            id=node_id,
            type="parallel",
            name="Parallel",
            data_inputs=[],
            data_outputs=[],
            ctrl_inputs=["in"],
            ctrl_outputs=ctrl_outputs,
            meta=self._build_meta(meta_data),
        )
        self._nodes[node_id] = node
        return node_id

    # ------------------------------------------------------------------
    # Control-flow namespace handling
    # ------------------------------------------------------------------

    def _handle_branch_namespaces(
        self,
        stmt: Branch,
        branch_node_id: str,
        stmts: list[Statement],
    ) -> None:
        """Process namespaces that follow a branch statement."""
        ns_map = self._find_namespaces(stmts)

        for port, label in [("true", stmt.true_label), ("false", stmt.false_label)]:
            ns = ns_map.get(label)
            if ns is not None:
                self._handled_namespaces.add(label)
                first_id = self._walk_statements(
                    ns.body, prev_node_id=None, in_namespace=True,
                    parent_branch_edge=(branch_node_id, port),
                )
                if first_id:
                    self._ensure_ctrl_ports(first_id, ctrl_in="in")
                    self._edges.append(
                        KGEdge(
                            type="control",
                            from_node=branch_node_id,
                            from_port=port,
                            to_node=first_id,
                            to_port="in",
                        )
                    )

    def _handle_switch_namespaces(
        self,
        stmt: Switch,
        switch_node_id: str,
        stmts: list[Statement],
    ) -> None:
        """Process namespaces that follow a switch statement."""
        ns_map = self._find_namespaces(stmts)
        node = self._nodes[switch_node_id]

        for i, (_, label) in enumerate(stmt.cases):
            port = node.ctrl_outputs[i] if i < len(node.ctrl_outputs) else f"case_{i}"
            ns = ns_map.get(label)
            if ns is not None:
                self._handled_namespaces.add(label)
                first_id = self._walk_statements(
                    ns.body, prev_node_id=None, in_namespace=True
                )
                if first_id:
                    self._ensure_ctrl_ports(first_id, ctrl_in="in")
                    self._edges.append(
                        KGEdge(
                            type="control",
                            from_node=switch_node_id,
                            from_port=port,
                            to_node=first_id,
                            to_port="in",
                        )
                    )

        if stmt.default_label:
            ns = ns_map.get(stmt.default_label)
            if ns is not None:
                self._handled_namespaces.add(stmt.default_label)
                first_id = self._walk_statements(
                    ns.body, prev_node_id=None, in_namespace=True
                )
                if first_id:
                    self._ensure_ctrl_ports(first_id, ctrl_in="in")
                    self._edges.append(
                        KGEdge(
                            type="control",
                            from_node=switch_node_id,
                            from_port="default",
                            to_node=first_id,
                            to_port="in",
                        )
                    )

    def _handle_parallel_namespaces(
        self,
        stmt: Parallel,
        parallel_node_id: str,
        stmts: list[Statement],
    ) -> None:
        """Process namespaces that follow a parallel statement."""
        ns_map = self._find_namespaces(stmts)
        node = self._nodes[parallel_node_id]

        for i, label in enumerate(stmt.labels):
            port = node.ctrl_outputs[i] if i < len(node.ctrl_outputs) else f"out_{i}"
            ns = ns_map.get(label)
            if ns is not None:
                self._handled_namespaces.add(label)
                first_id = self._walk_statements(
                    ns.body, prev_node_id=None, in_namespace=True
                )
                if first_id:
                    self._ensure_ctrl_ports(first_id, ctrl_in="in")
                    self._edges.append(
                        KGEdge(
                            type="control",
                            from_node=parallel_node_id,
                            from_port=port,
                            to_node=first_id,
                            to_port="in",
                        )
                    )

    # ------------------------------------------------------------------
    # Second pass: data edges
    # ------------------------------------------------------------------

    def _resolve_data_edges(
        self, stmts: list[Statement], known_ids: set[str]
    ) -> None:
        """Walk all statements and create data edges from variable references."""
        for stmt in stmts:
            if isinstance(stmt, DataflowBlock):
                self._resolve_data_edges(stmt.body, known_ids)
                continue
            if isinstance(stmt, Namespace):
                self._resolve_data_edges(stmt.body, known_ids)
                continue

            meta = _extract_meta(stmt)
            node_id = meta.get("node_id") if meta else None

            if isinstance(stmt, Assignment):
                # Infer node_id from target variable.
                if node_id is None:
                    parts = _parse_var_name(stmt.target, known_ids)
                    node_id = parts[0] if parts else None
                # An assignment's value may reference another node's output.
                if node_id and isinstance(stmt.value, Identifier):
                    src = self._var_to_node_port.get(stmt.value.name)
                    if src:
                        # Data edge from src to this value node's... but
                        # value nodes don't have data inputs.  Skip.
                        pass
                continue

            if node_id is None:
                continue
            node = self._nodes.get(node_id)
            if node is None:
                continue

            # Resolve data inputs.
            if isinstance(stmt, FuncCall):
                for i, inp in enumerate(stmt.inputs):
                    self._resolve_data_input(
                        inp, node, i, known_ids
                    )
            elif isinstance(stmt, Branch):
                self._resolve_data_input(
                    stmt.condition, node, 0, known_ids
                )
            elif isinstance(stmt, Switch):
                self._resolve_data_input(
                    stmt.value, node, 0, known_ids
                )

    def _resolve_data_input(
        self,
        expr: Expression,
        to_node: KGNode,
        input_idx: int,
        known_ids: set[str],
    ) -> None:
        """Create a data edge if the expression references a known output var."""
        idents = _extract_identifiers(expr)
        for ident_name in idents:
            src = self._var_to_node_port.get(ident_name)
            if src is None:
                continue

            src_node_id, src_port = src
            # Determine the target port name.
            if input_idx < len(to_node.data_inputs):
                to_port = to_node.data_inputs[input_idx].port
            else:
                to_port = f"in_{input_idx}"

            self._edges.append(
                KGEdge(
                    type="data",
                    from_node=src_node_id,
                    from_port=src_port,
                    to_node=to_node.id,
                    to_port=to_port,
                )
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gen_id(self, prefix: str) -> str:
        """Generate a unique node id."""
        self._node_counter += 1
        return f"{prefix}_{self._node_counter}"

    def _find_namespaces(self, stmts: list[Statement]) -> dict[str, Namespace]:
        """Build a map of namespace name -> Namespace from a statement list."""
        result: dict[str, Namespace] = {}
        for stmt in stmts:
            if isinstance(stmt, Namespace):
                result[stmt.name] = stmt
        return result

    def _build_meta(self, meta_data: dict[str, Any] | None) -> dict[str, Any]:
        """Build the meta dict for a KGNode from @meta annotation data."""
        if not meta_data:
            # No meta — assign a spread-out default position
            self._auto_pos_counter = getattr(self, "_auto_pos_counter", 0) + 1
            col = (self._auto_pos_counter - 1) % 4
            row = (self._auto_pos_counter - 1) // 4
            return {"pos": [100 + col * 220, 100 + row * 160], "size": [180, 120]}
        result: dict[str, Any] = {}
        if "pos" in meta_data:
            pos = meta_data["pos"]
            result["pos"] = list(pos) if isinstance(pos, tuple) else pos
        if "pos" not in result:
            self._auto_pos_counter = getattr(self, "_auto_pos_counter", 0) + 1
            col = (self._auto_pos_counter - 1) % 4
            row = (self._auto_pos_counter - 1) // 4
            result["pos"] = [100 + col * 220, 100 + row * 160]
        for key, val in meta_data.items():
            if key not in ("node_id", "pos"):
                result[key] = val
        return result

    def _infer_input_port_name(self, index: int, stmt: FuncCall) -> str:
        """Infer a port name for a positional input."""
        # Single-input nodes commonly use "value"
        if len(stmt.inputs) == 1:
            return "value"
        # Two-input nodes: a, b
        if index < 26:
            return chr(ord("a") + index)
        return f"in_{index}"

    def _ensure_ctrl_ports(self, node_id: str, ctrl_in: str = "in") -> None:
        """Ensure a node has the required control input port."""
        node = self._nodes.get(node_id)
        if node and ctrl_in not in node.ctrl_inputs:
            node.ctrl_inputs.append(ctrl_in)
