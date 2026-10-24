"""Text -> graph view: a program as node graphs (graph.md)."""

from kohakunode.errors import KirGraphError
from kohakunode.flow.cfg import UNDEF, build_cfg, reaching
from kohakunode.sig.env import NodeEnv, Resolved
from kohakunode.sig.types import type_text
from kohakunode.syntax.ast import (
    Assign,
    Branch,
    Call,
    Collect,
    Dataflow,
    Def,
    Each,
    Jump,
    Literal,
    Name,
    Namespace,
    Origin,
    Parallel,
    Program,
    Stmt,
    Switch,
    Try,
    TypeHints,
    children,
)
from kohakunode.syntax.writer import write_type

FORMAT = 3
DATA_STYLES = ("wires", "variables")

Port = tuple[str, str]  # (node id, port name)


def _paths(body: list[Stmt], prefix: str, out: dict) -> None:
    """``id(stmt) -> (path, structural path)``: the path is the statement's origin id
    (``meta.node_id``, else the structural path), as ``stamp_origins`` assigns it."""
    for index, stmt in enumerate(body):
        node_path = f"{prefix}/{index}"
        node_id = stmt.meta.get("node_id")
        out[id(stmt)] = (node_path if node_id is None else str(node_id), node_path)
        for child_index, block in enumerate(children(stmt)):
            _paths(block, f"{node_path}/{'body' if child_index == 0 else 'handler'}", out)


class _Scope:
    """Builds one graph: the top level or one `@def`."""

    def __init__(
        self,
        env: NodeEnv | None,
        name: str,
        body: list[Stmt],
        params=(),
        outputs=(),
        data: str = "wires",
        prefix: str = "body",
    ):
        self.env = env
        self.name = name
        self.variables = data == "variables"
        # With variables, reads and writes wait until every write has its node (`resolve_variables`)
        self.var_reads: list[tuple[int, str, Port, str | None]] = []
        self.var_writes: list[tuple[Port, str, str | None]] = []
        self.body = body
        self.params = list(params)
        self.outputs = list(outputs)
        self.paths: dict[int, tuple[str, str]] = {}
        _paths(body, prefix, self.paths)
        self.regions: list[dict] = []
        self.region: str | None = None
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.count = 0
        self.ids: set[str] = set()
        self.stmt_node: dict[int, str] = {}
        self.merges: dict[str, str] = {}  # namespace label -> labelled merge node
        self.pending: dict[int, list[Port]] = {}  # id(namespace) -> ports continuing after it
        self.emitted: set[int] = set()
        self.stack: list[list[Stmt]] = []
        self.cfg = build_cfg(body, tuple(p.name for p in self.params))
        self.inn = reaching(self.cfg)
        self.inn_forward = reaching(self.cfg, forward=True) if self.variables else self.inn
        self.multi: set[str] = set()  # names with a read reached by several writes
        for n in self.cfg.reachable():
            for x in self.cfg.nodes[n].reads:
                if len({d for y, d in self.inn[n] if y == x} - {UNDEF}) > 1:
                    self.multi.add(x)
        if self.outputs:
            for o in self.outputs:
                if len({d for y, d in self.inn[self.cfg.exit] if y == o.name} - {UNDEF}) > 1:
                    self.multi.add(o.name)

    # ------------------------------------------------------------ nodes and edges
    def new_id(self, base: str, stmt: Stmt | None = None) -> str:
        self.count += 1
        if stmt is not None and "node_id" in stmt.meta:
            nid = str(stmt.meta["node_id"])
        else:
            nid = f"{base.replace('.', '_')}_{self.count}"
        while nid in self.ids:
            nid += "_"
        self.ids.add(nid)
        return nid

    def node(self, kind: str, base: str, stmt: Stmt | None = None, **fields) -> dict:
        n = {"id": self.new_id(base, stmt), "kind": kind}
        n.update(fields)
        if stmt is not None:
            meta = {k: v for k, v in stmt.meta.items() if k != "node_id"}
            if meta:
                n["meta"] = {k: list(v) if isinstance(v, tuple) else v for k, v in meta.items()}
            if stmt.hint:
                n["hints"] = dict(stmt.hint)
            if stmt.origin is not None:
                n["origin"] = _origin(stmt.origin)
            n["path"] = self.paths[id(stmt)][0]
            self.stmt_node[id(stmt)] = n["id"]
        if self.region is not None:
            n["region"] = self.region
        self.nodes.append(n)
        return n

    def open_region(
        self, rid: str, kind: str, owner: Port | None, label: str | None = None
    ) -> str | None:
        """Enter region ``rid``; the region it was opened in is returned for ``close``."""
        r: dict = {"id": rid, "kind": kind}
        if self.region is not None:
            r["parent"] = self.region
        if owner is not None:
            r["owner"] = {"node": owner[0], "port": owner[1]}
        if label is not None:
            r["label"] = label
        self.regions.append(r)
        outer, self.region = self.region, rid
        return outer

    def ctrl(self, src: Port, dst: Port) -> None:
        self.edges.append(
            {
                "kind": "ctrl",
                "from": {"node": src[0], "port": src[1]},
                "to": {"node": dst[0], "port": dst[1]},
            }
        )

    def data(self, src: Port, dst: Port) -> None:
        self.edges.append(
            {
                "kind": "data",
                "from": {"node": src[0], "port": src[1]},
                "to": {"node": dst[0], "port": dst[1]},
            }
        )

    def join(self, incoming: list[Port], target: Port) -> None:
        """Connect incoming control to ``target``, through a merge node when several."""
        if len(incoming) > 1:
            m = self.node(
                "merge",
                "merge",
                ctrl_in=[f"in_{i}" for i in range(len(incoming))],
                ctrl_out=["out"],
            )
            for i, p in enumerate(incoming):
                self.ctrl(p, (m["id"], f"in_{i}"))
            incoming = [(m["id"], "out")]
        for p in incoming:
            self.ctrl(p, target)

    # ------------------------------------------------------------ data
    def writer_port(self, def_node: int, name: str) -> Port | None:
        if def_node == self.cfg.entry:
            return ("inputs", name)
        node = self.cfg.nodes[def_node]
        if node.kind == "bind":
            for owner_id, bind in self.cfg.binds.items():
                if bind == def_node:
                    nid = self.stmt_node.get(owner_id)
                    if nid is None:
                        return None
                    owner = next(n for n in self.nodes if n["id"] == nid)
                    if owner["kind"] == "try":
                        return (nid, "error")
                    return (nid, "item" if owner["props"].get("item") == name else "index")
            return None
        s = node.stmt
        nid = self.stmt_node.get(id(s))
        if nid is None:
            return None
        if isinstance(s, Assign):
            return (nid, "value")
        n = next(x for x in self.nodes if x["id"] == nid)
        # Output ports follow the statement's outputs in order (a port names its variable only in wires)
        if isinstance(s, Call):
            for o, p in zip(s.outs, n["outputs"]):
                if o == name:
                    return (nid, p["port"])
        for p in n["outputs"]:
            if p.get("var") == name:
                return (nid, p["port"])
        return None

    def wire_read(self, cfg_node: int, name: str, target: Port) -> None:
        """A read: a direct wire from its only write, or a `get` variable node. With
        variables it waits until every write has its node (`resolve_variables`)."""
        if self.variables:
            self.var_reads.append((cfg_node, name, target, self.region))
            return
        if not self.variables and name not in self.multi:
            defs = {d for y, d in self.inn[cfg_node] if y == name} - {UNDEF}
            if len(defs) == 1:
                src = self.writer_port(next(iter(defs)), name)
                if src is not None:
                    self.data(src, target)
                    return
        self.get_node(name, target)

    def get_node(self, name: str, target: Port) -> None:
        g = self.node("get", "get", props={"name": name}, outputs=[{"port": "value"}])
        self.data((g["id"], "value"), target)

    def resolve_variables(self) -> None:
        """The variables style's reads and writes, once every write has its node.

        Inside the graph a value goes through its variable: a `get` reads it, a `set` is
        drawn for every write of a name some `get` reads. The graph's own inputs and
        outputs are never wired to a variable. A read only the input reaches on the way
        in (`reaching(forward=True)`: inside a loop, what entered it) is wired from the
        input; a graph output only one write decides (the input left out when the program
        writes the name) is wired from that write. Otherwise an assign statement (`join`)
        stands where the value is decided: for an output, right before the end, reading
        the variable; for an input other writes meet, right after the start, writing it.
        """
        read_names: set[str] = set()
        init_names: list[str] = []
        for cfg_node, name, target, region in self.var_reads:
            at_exit = cfg_node == self.cfg.exit
            defs = sorted(
                {d for y, d in (self.inn if at_exit else self.inn_forward)[cfg_node] if y == name}
                - {UNDEF}
            )
            if at_exit and any(d != self.cfg.entry for d in defs):
                defs = [d for d in defs if d != self.cfg.entry]
            srcs = [self.writer_port(d, name) for d in defs]
            if len(defs) == 1 and srcs[0] is not None and (at_exit or defs[0] == self.cfg.entry):
                self.data(srcs[0], target)
                continue
            if self.cfg.entry in defs and name not in init_names:
                init_names.append(name)
            if at_exit and defs:
                j = self.assign_on_flow(name, target[0], before=True)
                self.data((j, "value"), target)
                target = (j, "value")
            outer, self.region = self.region, region if not at_exit else None
            self.get_node(name, target)
            self.region = outer
            read_names.add(name)
        for name in init_names:
            j = self.assign_on_flow(name, "inputs", before=False)
            self.data(("inputs", name), (j, "value"))
            self.var_writes.append(((j, "value"), name, None))
        for src, name, region in self.var_writes:
            if name in read_names:
                outer, self.region = self.region, region
                st = self.node("set", "set", props={"name": name}, inputs=[{"port": "value"}])
                self.data(src, (st["id"], "value"))
                self.region = outer
                continue
            # A write nothing reads keeps its name on its own port (`var` right after `port`)
            node = next(n for n in self.nodes if n["id"] == src[0])
            node["outputs"] = [
                (
                    {"port": p["port"], "var": name, **{k: v for k, v in p.items() if k != "port"}}
                    if p["port"] == src[1]
                    else p
                )
                for p in node.get("outputs", [])
            ]

    def assign_on_flow(self, name: str, at: str, before: bool) -> str:
        """An assign statement (`join`, one input) of ``name`` spliced into the control flow
        right before node ``at`` (into its ``in``) or right after it (out of its ``out``)."""
        j = self.node(
            "join",
            "join",
            props={"name": name},
            inputs=[{"port": "value"}],
            outputs=[{"port": "value"}],
            ctrl_in=["in"],
            ctrl_out=["out"],
        )["id"]
        end = {"node": at, "port": "in" if before else "out"}
        for e in self.edges:
            if e["kind"] == "ctrl" and e["to" if before else "from"] == end:
                e["to" if before else "from"] = {"node": j, "port": "in" if before else "out"}
        if before:
            self.ctrl((j, "out"), (at, "in"))
        else:
            self.ctrl((at, "out"), (j, "in"))
        return j

    def out_entry(self, port: str, name: str | None, ptype: str | None = None) -> dict:
        """An output port; with variables, a written name is shown by its `set` node instead."""
        entry: dict = {"port": port}
        if name is None:
            entry["var"] = None
        elif not self.variables:
            entry["var"] = name
        if ptype is not None:
            entry["type"] = ptype
        return entry

    def bind_out(self, src: Port, name: str | None) -> None:
        """A write: a `set` variable node on the output port (with variables, or for a name
        written on several paths)."""
        if name is None or not (self.variables or name in self.multi):
            return
        if self.variables:
            # The graph's inputs reach their readers directly (`resolve_variables`)
            if src[0] != "inputs":
                self.var_writes.append((src, name, self.region))
            return
        st = self.node("set", "set", props={"name": name}, inputs=[{"port": "value"}])
        self.data(src, (st["id"], "value"))

    # ------------------------------------------------------------ statements
    def ports_of(self, s: Call) -> tuple[list[dict], list[dict]]:
        sig = None
        if self.env is not None:
            r = self.env.resolve(s.name)
            if isinstance(r, Resolved):
                sig = r.signature
        ins = []
        pos_i = 0
        for a in s.args:
            if a.key is None:
                port = sig.inputs[pos_i].name if sig and pos_i < len(sig.inputs) else f"in{pos_i}"
                ptype = sig.inputs[pos_i].type if sig and pos_i < len(sig.inputs) else None
                pos_i += 1
                entry = {"port": port}
            else:
                port = a.key
                ptype = sig.input(a.key).type if sig and sig.input(a.key) else None
                entry = {"port": port, "keyword": True}
            if ptype is not None and ptype.kind != "any":
                entry["type"] = type_text(ptype)
            if isinstance(a.value, Literal):
                entry["value"] = _json_literal(a.value.value)
            ins.append(entry)
        outs = []
        for i, o in enumerate(s.outs):
            port = sig.outputs[i].name if sig and i < len(sig.outputs) else f"out{i}"
            ptype = sig.outputs[i].type if sig and i < len(sig.outputs) else None
            text = type_text(ptype) if ptype is not None and ptype.kind != "any" else None
            outs.append(self.out_entry(port, o, text))
        return ins, outs

    def simple(self, s: Stmt, on_chain: bool) -> dict:
        ctrl = (
            {"ctrl_in": ["in"], "ctrl_out": ["out"]}
            if on_chain
            else {"ctrl_in": [], "ctrl_out": []}
        )
        if isinstance(s, Call):
            ins, outs = self.ports_of(s)
            return self.node("call", s.name, s, name=s.name, inputs=ins, outputs=outs, **ctrl)
        # `x = 10` / `x = y`: the assign command, value in, variable out.
        inp: dict = {"port": "value"}
        if isinstance(s.value, Literal):
            inp["value"] = _json_literal(s.value.value)
        ptype = write_type(s.type) if s.type is not None else None
        return self.node(
            "assign",
            "assign",
            s,
            inputs=[inp],
            outputs=[self.out_entry("value", s.target, ptype)],
            **ctrl,
        )

    def bind_outs(self, s: Stmt, n: dict) -> None:
        names = [s.target] if isinstance(s, Assign) else list(s.outs)
        for name, port in zip(names, n["outputs"]):
            self.bind_out((n["id"], port["port"]), name)

    def wire_simple_inputs(self, s: Stmt, n: dict) -> None:
        cfg_n = self.cfg.node_of.get(id(s))
        if isinstance(s, Call):
            for a, port in zip(s.args, n["inputs"]):
                if isinstance(a.value, Name) and cfg_n is not None:
                    self.wire_read(cfg_n, a.value.id, (n["id"], port["port"]))
        elif isinstance(s, Assign) and isinstance(s.value, Name) and cfg_n is not None:
            self.wire_read(cfg_n, s.value.id, (n["id"], "value"))

    def block(self, stmts: list[Stmt], incoming: list[Port]) -> list[Port]:
        self.stack.append(stmts)
        try:
            return self._block(stmts, incoming)
        finally:
            self.stack.pop()

    def _block(self, stmts: list[Stmt], incoming: list[Port]) -> list[Port]:
        local = {s.label: s for s in stmts if isinstance(s, Namespace)}
        for s in stmts:
            match s:
                case Def() | TypeHints():
                    continue
                case Namespace():
                    if id(s) not in self.emitted:
                        # A collect body can be declared before its controller.
                        # Its body runs from the collect, never by declaration order.
                        if any(
                            isinstance(owner, Collect) for owner in self.cfg.owners.get(id(s), [])
                        ):
                            continue
                        # Never entered: keep it as an unreachable labelled chain.
                        m = self.labelled_merge(s)
                        self.pending.setdefault(id(s), []).extend(self.namespace(s, [(m, "out")]))
                    incoming = incoming + self.pending.pop(id(s), [])
                case Assign() | Call():
                    n = self.simple(s, True)
                    self.wire_simple_inputs(s, n)
                    self.join(incoming, (n["id"], "in"))
                    self.bind_outs(s, n)
                    incoming = [(n["id"], "out")]
                case Dataflow():
                    # The members sit in the block's region; its owner is the dataflow node
                    region = len(self.regions)
                    outer = self.open_region(f"{self.paths[id(s)][1]}/body", "dataflow", None)
                    members = []
                    for inner in s.body:
                        members.append(self.simple(inner, False))
                    for inner, m in zip(s.body, members):
                        self.wire_simple_inputs(inner, m)
                        self.bind_outs(inner, m)
                    self.region = outer
                    g = self.node(
                        "dataflow",
                        "dataflow",
                        s,
                        props={"members": [m["id"] for m in members]},
                        ctrl_in=["in"],
                        ctrl_out=["out"],
                    )
                    self.regions[region]["owner"] = {"node": g["id"], "port": None}
                    self.join(incoming, (g["id"], "in"))
                    incoming = [(g["id"], "out")]
                case Branch():
                    n = self.node(
                        "branch",
                        "branch",
                        s,
                        props={"labels": {"true": s.true_label, "false": s.false_label}},
                        inputs=[{"port": "cond"}],
                        ctrl_in=["in"],
                        ctrl_out=["true", "false"],
                    )
                    self.read_expr(s, s.cond, (n["id"], "cond"), n["inputs"][0])
                    self.join(incoming, (n["id"], "in"))
                    incoming = []
                    for port, label in (("true", s.true_label), ("false", s.false_label)):
                        self.enter(local, label, (n["id"], port))
                case Switch():
                    ports = [f"case_{i}" for i in range(len(s.cases))] + (
                        ["default"] if s.default else []
                    )
                    labels = [label for _, label in s.cases] + ([s.default] if s.default else [])
                    n = self.node(
                        "switch",
                        "switch",
                        s,
                        props={
                            "cases": [_json_literal(v) for v, _ in s.cases],
                            "labels": dict(zip(ports, labels)),
                        },
                        inputs=[{"port": "value"}],
                        ctrl_in=["in"],
                        ctrl_out=ports,
                    )
                    self.read_expr(s, s.value, (n["id"], "value"), n["inputs"][0])
                    self.join(incoming, (n["id"], "in"))
                    incoming = []
                    for port, label in zip(ports, labels):
                        self.enter(local, label, (n["id"], port))
                case Parallel():
                    ports = [f"out_{i}" for i in range(len(s.labels))]
                    n = self.node(
                        "parallel",
                        "parallel",
                        s,
                        props={"labels": dict(zip(ports, s.labels))},
                        ctrl_in=["in"],
                        ctrl_out=ports,
                    )
                    self.join(incoming, (n["id"], "in"))
                    incoming = []
                    for port, label in zip(ports, s.labels):
                        ns = local.get(label)
                        if ns is not None:
                            self.emitted.add(id(ns))
                            incoming += self.namespace(ns, [(n["id"], port)])
                case Each() | Collect():
                    collecting = isinstance(s, Collect)
                    kind = "collect" if collecting else "each"
                    props = {
                        "label": s.label,
                        "item": s.item,
                        "index": s.index,
                        "has_index": s.has_index,
                    }
                    inputs = [{"port": "items"}]
                    outputs = [self.out_entry("item", s.item), self.out_entry("index", s.index)]
                    if collecting:
                        props["target"] = s.target
                        inputs.append({"port": "value", "deferred": "body_end"})
                        outputs.append(self.out_entry("results", s.target))
                    n = self.node(
                        kind,
                        kind,
                        s,
                        props=props,
                        inputs=inputs,
                        outputs=outputs,
                        ctrl_in=["in", "next"],
                        ctrl_out=["body", "done"],
                    )
                    self.read_expr(s, s.items, (n["id"], "items"), n["inputs"][0])
                    self.join(incoming, (n["id"], "in"))
                    self.bind_out((n["id"], "item"), s.item)
                    self.bind_out((n["id"], "index"), s.index)
                    if collecting:
                        self.bind_out((n["id"], "results"), s.target)
                    ns = local.get(s.label)
                    if ns is not None:
                        self.emitted.add(id(ns))
                        ends = self.namespace(ns, [(n["id"], "body")])
                        self.join(ends, (n["id"], "next"))
                    if collecting:
                        # This input is sampled only after the namespace ends.
                        # Emit its wire after all body writers have graph nodes.
                        if isinstance(s.value, Literal):
                            inputs[1]["value"] = _json_literal(s.value.value)
                        else:
                            self.wire_read(self.cfg.samples[id(s)], s.value.id, (n["id"], "value"))
                    incoming = [(n["id"], "done")]
                case Jump():
                    edge_start = len(self.edges)
                    target = self.find_namespace(s.label)
                    if target is None:
                        incoming = []
                        continue
                    if s.label not in self.merges:
                        if id(target) in self.emitted:
                            raise KirGraphError(
                                f"namespace `{s.label}` is entered both by a builtin and by "
                                "jump; a graph cannot draw that"
                            )
                        m = self.labelled_merge(target, s)
                        self.join(incoming, (m, "in_0"))
                        jump_edges = self.edges[edge_start:]
                        self.pending.setdefault(id(target), []).extend(
                            self.namespace(target, [(m, "out")])
                        )
                    else:
                        self.loop_back(s.label, incoming)
                        jump_edges = self.edges[edge_start:]
                    mid = self.merges[s.label]
                    if not incoming and any(
                        node == self.cfg.node_of.get(id(s))
                        for node, _ in self.cfg.succ[self.cfg.entry]
                    ):
                        # Unlike a back edge, entry has no predecessor node. A
                        # marker distinguishes an initial jump from an unentered
                        # namespace with otherwise identical topology.
                        merge = next(n for n in self.nodes if n["id"] == mid)
                        merge["entry"] = True
                        if s.origin is not None:
                            merge["origin"] = _origin(s.origin)
                    if s.origin is not None:
                        # Jumps are edges, not runtime nodes. Keep their provenance
                        # on the edge entering the labelled merge (including back edges).
                        for edge in jump_edges:
                            if edge["kind"] == "ctrl" and edge["to"]["node"] == mid:
                                edge["origin"] = _origin(s.origin)
                    incoming = []
                case Try():
                    n = self.node(
                        "try",
                        "try",
                        s,
                        props={"error_name": s.error_name},
                        outputs=[self.out_entry("error", s.error_name)] if s.error_name else [],
                        ctrl_in=["in"],
                        ctrl_out=["try", "except"],
                    )
                    self.join(incoming, (n["id"], "in"))
                    self.bind_out((n["id"], "error"), s.error_name)
                    base = self.paths[id(s)][1]
                    outer = self.open_region(f"{base}/body", "try", (n["id"], "try"))
                    a = self.block(s.body, [(n["id"], "try")])
                    self.region = outer
                    self.open_region(f"{base}/handler", "try", (n["id"], "except"))
                    b = self.block(s.handler, [(n["id"], "except")])
                    self.region = outer
                    incoming = a + b
        return incoming

    def read_expr(self, s: Stmt, e, target: Port, port_entry: dict) -> None:
        if isinstance(e, Literal):
            port_entry["value"] = _json_literal(e.value)
            return
        cfg_n = self.cfg.node_of.get(id(s))
        if cfg_n is not None:
            self.wire_read(cfg_n, e.id, target)

    def labelled_merge(self, ns: Namespace, stmt: Stmt | None = None) -> str:
        m = self.node(
            "merge", "merge", stmt, props={"label": ns.label}, ctrl_in=["in_0"], ctrl_out=["out"]
        )
        self.merges[ns.label] = m["id"]
        self.emitted.add(id(ns))
        return m["id"]

    def loop_back(self, label: str, incoming: list[Port]) -> None:
        mid = self.merges[label]
        m = next(n for n in self.nodes if n["id"] == mid)
        for p in incoming:
            port = f"in_{len(m['ctrl_in'])}"
            m["ctrl_in"].append(port)
            self.ctrl(p, (mid, port))

    def enter(self, local: dict, label: str, src: Port) -> None:
        ns = local.get(label)
        if ns is None:
            return
        self.emitted.add(id(ns))
        self.pending.setdefault(id(ns), []).extend(self.namespace(ns, [src]))

    def namespace(self, ns: Namespace, incoming: list[Port]) -> list[Port]:
        if ns.origin is not None:
            for nid, port in incoming:
                node = next(n for n in self.nodes if n["id"] == nid)
                node.setdefault("namespace_origins", {})[port] = _origin(ns.origin)

        # The body's region is owned by the port that enters it, of the owner's kind
        owner = incoming[0]
        kind = next(n for n in self.nodes if n["id"] == owner[0])["kind"]
        outer = self.open_region(self.paths[id(ns)][0], kind, owner, ns.label)
        try:
            return self.block(ns.body, incoming)
        finally:
            self.region = outer

    def find_namespace(self, label: str) -> Namespace | None:
        """Like `jump`: the current block first, then each enclosing block."""
        for stmts in reversed(self.stack):
            for s in stmts:
                if isinstance(s, Namespace) and s.label == label:
                    return s
        return None

    # ------------------------------------------------------------ whole graph
    def build(self) -> dict:
        start: list[Port] = []
        if self.params is not None and self.name != "main":
            outs = [
                self.out_entry(p.name, p.name, write_type(p.type) if p.type is not None else None)
                for p in self.params
            ]
            self.nodes.append(
                {
                    "id": "inputs",
                    "kind": "inputs",
                    "outputs": outs,
                    "ctrl_in": [],
                    "ctrl_out": ["out"],
                }
            )
            self.ids.add("inputs")
            start = [("inputs", "out")]
            for p in self.params:
                self.bind_out(("inputs", p.name), p.name)
        end = self.block(self.body, start)
        if self.name != "main":
            ins = [
                {"port": o.name, **({"type": write_type(o.type)} if o.type is not None else {})}
                for o in self.outputs
            ]
            self.nodes.append(
                {
                    "id": "outputs",
                    "kind": "outputs",
                    "inputs": ins,
                    "ctrl_in": ["in"],
                    "ctrl_out": [],
                }
            )
            self.ids.add("outputs")
            self.join(end, ("outputs", "in"))
            for o in self.outputs:
                self.wire_read(self.cfg.exit, o.name, ("outputs", o.name))
        if self.variables:
            self.resolve_variables()
        self.edges.sort(
            key=lambda e: (e["to"]["node"], e["to"]["port"], e["from"]["node"], e["from"]["port"])
        )
        g = {"name": self.name, "nodes": self.nodes, "edges": self.edges}
        if self.regions:
            g["regions"] = self.regions
        if self.name != "main":
            g["params"] = [
                {
                    "name": p.name,
                    **({"type": write_type(p.type)} if p.type is not None else {}),
                    **(
                        {"default": _json_literal(p.default.value)}
                        if isinstance(p.default, Literal)
                        else {}
                    ),
                }
                for p in self.params
            ]
            g["outputs"] = [
                {"name": o.name, **({"type": write_type(o.type)} if o.type is not None else {})}
                for o in self.outputs
            ]
        return g


def _origin(origin: Origin) -> dict:
    """Provenance is JSON data, never editor metadata or a KIR literal."""
    return {
        "module": origin.module,
        "node_id": origin.node_id,
        "line": origin.line,
        "definition": origin.definition,
        "calls": [_origin(call) for call in origin.calls],
        "generated": origin.generated,
    }


def _json_literal(v):
    if isinstance(v, tuple):
        return {"tuple": [_json_literal(x) for x in v]}
    if isinstance(v, list):
        return [_json_literal(x) for x in v]
    if isinstance(v, dict):
        if all(isinstance(k, str) for k in v):
            return {"dict": {k: _json_literal(x) for k, x in v.items()}}
        return {"pairs": [[_json_literal(k), _json_literal(x)] for k, x in v.items()]}
    return v


def to_graph(program: Program, env: NodeEnv | None = None, data: str = "wires") -> dict:
    """The graph view of a program.

    ``data="wires"`` wires a read straight to its only write; ``data="variables"`` draws
    a value inside the graph through its variable (`get` and `set` nodes) and wires the
    graph's own inputs and outputs straight to the statements they reach
    (`_Scope.resolve_variables`).
    """
    if data not in DATA_STYLES:
        raise ValueError(f"unknown data style {data!r}; known: {list(DATA_STYLES)}")
    graphs = [_Scope(env, "main", program.body, data=data).build()]
    for index, s in enumerate(program.body):
        if isinstance(s, Def):
            prefix = f"body/{index}/body"
            graph = _Scope(env, s.name, s.body, s.params, s.outputs, data, prefix).build()
            if s.origin is not None:
                graph["origin"] = _origin(s.origin)
            graphs.append(graph)
    out = {
        "kirgraph": FORMAT,
        "uses": [{"library": u.library, "alias": u.alias} for u in program.uses],
        "graphs": graphs,
    }
    if program.imports:
        out["imports"] = [{"module": imp.module, "alias": imp.alias} for imp in program.imports]
    if program.exports:
        out["exports"] = list(program.exports)
    if program.mode:
        out["mode"] = program.mode
    hints = [s for s in program.body if isinstance(s, TypeHints)]
    if hints:
        out["typehints"] = [
            {
                "name": e.name,
                "inputs": [write_type(t) for t in e.inputs],
                "outputs": [write_type(t) for t in e.outputs],
            }
            for h in hints
            for e in h.entries
        ]
        if any(h.origin is not None for h in hints):
            out["typehint_groups"] = [
                {
                    "count": len(h.entries),
                    **({"origin": _origin(h.origin)} if h.origin is not None else {}),
                }
                for h in hints
            ]
    return out
