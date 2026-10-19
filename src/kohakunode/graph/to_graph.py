"""Text -> graph view: a program as node graphs (graph.md)."""

from kohakunode.errors import KirGraphError
from kohakunode.flow.cfg import UNDEF, build_cfg, reaching
from kohakunode.sig.env import NodeEnv, Resolved
from kohakunode.sig.types import type_text
from kohakunode.syntax.ast import (
    Assign,
    Branch,
    Call,
    Dataflow,
    Def,
    Each,
    Jump,
    Literal,
    Name,
    Namespace,
    Parallel,
    Program,
    Stmt,
    Switch,
    Try,
    TypeHints,
)
from kohakunode.syntax.writer import write_type

FORMAT = 2

Port = tuple[str, str]  # (node id, port name)


class _Scope:
    """Builds one graph: the top level or one `@def`."""

    def __init__(self, env: NodeEnv | None, name: str, body: list[Stmt], params=(), outputs=()):
        self.env = env
        self.name = name
        self.body = body
        self.params = list(params)
        self.outputs = list(outputs)
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
            self.stmt_node[id(stmt)] = n["id"]
        self.nodes.append(n)
        return n

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
        for p in n["outputs"]:
            if p.get("var") == name:
                return (nid, p["port"])
        return None

    def wire_read(self, cfg_node: int, name: str, target: Port) -> None:
        if name in self.multi:
            g = self.node(
                "get", "get", props={"name": name}, outputs=[{"port": "value", "var": name}]
            )
            self.data((g["id"], "value"), target)
            return
        defs = {d for y, d in self.inn[cfg_node] if y == name} - {UNDEF}
        if len(defs) == 1:
            src = self.writer_port(next(iter(defs)), name)
            if src is not None:
                self.data(src, target)
                return
        g = self.node("get", "get", props={"name": name}, outputs=[{"port": "value", "var": name}])
        self.data((g["id"], "value"), target)

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
            entry = {"port": port, "var": o}
            ptype = sig.outputs[i].type if sig and i < len(sig.outputs) else None
            if ptype is not None and ptype.kind != "any":
                entry["type"] = type_text(ptype)
            outs.append(entry)
        return ins, outs

    def simple(self, s: Stmt, on_chain: bool) -> dict:
        ctrl = (
            {"ctrl_in": ["in"], "ctrl_out": ["out"]}
            if on_chain
            else {"ctrl_in": [], "ctrl_out": []}
        )
        if isinstance(s, Call):
            ins, outs = self.ports_of(s)
            n = self.node("call", s.name, s, name=s.name, inputs=ins, outputs=outs, **ctrl)
        elif isinstance(s.value, Literal):
            out = {"port": "value", "var": s.target}
            if s.type is not None:
                out["type"] = write_type(s.type)
            n = self.node(
                "value",
                "value",
                s,
                props={"value": _json_literal(s.value.value)},
                outputs=[out],
                **ctrl,
            )
        else:
            n = self.node(
                "set",
                "set",
                s,
                props={"name": s.target, "copy": True},
                inputs=[{"port": "value"}],
                outputs=[{"port": "value", "var": s.target}],
                **ctrl,
            )
        return n

    def wire_simple_inputs(self, s: Stmt, n: dict) -> None:
        cfg_n = self.cfg.node_of.get(id(s))
        if isinstance(s, Call):
            for a, port in zip(s.args, n["inputs"]):
                if isinstance(a.value, Name) and cfg_n is not None:
                    self.wire_read(cfg_n, a.value.id, (n["id"], port["port"]))
        elif isinstance(s, Assign) and isinstance(s.value, Name) and cfg_n is not None:
            self.wire_read(cfg_n, s.value.id, (n["id"], "value"))

    def sets_after(self, names: list[str], incoming: list[Port], src_of) -> list[Port]:
        """Chain a set node after a write of each multi-path name."""
        for x in names:
            if x is None or x not in self.multi:
                continue
            st = self.node(
                "set",
                "set",
                props={"name": x},
                inputs=[{"port": "value"}],
                ctrl_in=["in"],
                ctrl_out=["out"],
            )
            self.data(src_of(x), (st["id"], "value"))
            self.join(incoming, (st["id"], "in"))
            incoming = [(st["id"], "out")]
        return incoming

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
                        # Never entered: keep it as an unreachable labelled chain.
                        m = self.labelled_merge(s)
                        self.pending.setdefault(id(s), []).extend(self.namespace(s, [(m, "out")]))
                    incoming = incoming + self.pending.pop(id(s), [])
                case Assign() | Call():
                    n = self.simple(s, True)
                    self.wire_simple_inputs(s, n)
                    self.join(incoming, (n["id"], "in"))
                    outs = [s.target] if isinstance(s, Assign) else list(s.outs)
                    incoming = self.sets_after(
                        outs, [(n["id"], "out")], lambda x, n=n, s=s: self.out_port(n, x)
                    )
                case Dataflow():
                    members = []
                    for inner in s.body:
                        members.append(self.simple(inner, False))
                    for inner, m in zip(s.body, members):
                        self.wire_simple_inputs(inner, m)
                    g = self.node(
                        "dataflow",
                        "dataflow",
                        s,
                        props={"members": [m["id"] for m in members]},
                        ctrl_in=["in"],
                        ctrl_out=["out"],
                    )
                    self.join(incoming, (g["id"], "in"))
                    incoming = [(g["id"], "out")]
                    for inner, m in zip(s.body, members):
                        outs = [inner.target] if isinstance(inner, Assign) else list(inner.outs)
                        incoming = self.sets_after(
                            outs, incoming, lambda x, m=m: self.out_port(m, x)
                        )
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
                case Each():
                    n = self.node(
                        "each",
                        "each",
                        s,
                        props={
                            "label": s.label,
                            "item": s.item,
                            "index": s.index,
                            "has_index": s.has_index,
                        },
                        inputs=[{"port": "items"}],
                        outputs=[
                            {"port": "item", "var": s.item},
                            {"port": "index", "var": s.index},
                        ],
                        ctrl_in=["in", "next"],
                        ctrl_out=["body", "done"],
                    )
                    self.read_expr(s, s.items, (n["id"], "items"), n["inputs"][0])
                    self.join(incoming, (n["id"], "in"))
                    ns = local.get(s.label)
                    if ns is not None:
                        self.emitted.add(id(ns))
                        start = self.sets_after(
                            [s.item, s.index],
                            [(n["id"], "body")],
                            lambda x, n=n, s=s: (n["id"], "item" if x == s.item else "index"),
                        )
                        ends = self.namespace(ns, start)
                        self.join(ends, (n["id"], "next"))
                    incoming = [(n["id"], "done")]
                case Jump():
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
                        self.pending.setdefault(id(target), []).extend(
                            self.namespace(target, [(m, "out")])
                        )
                    else:
                        self.loop_back(s.label, incoming)
                    incoming = []
                case Try():
                    n = self.node(
                        "try",
                        "try",
                        s,
                        props={"error_name": s.error_name},
                        outputs=[{"port": "error", "var": s.error_name}] if s.error_name else [],
                        ctrl_in=["in"],
                        ctrl_out=["try", "except"],
                    )
                    self.join(incoming, (n["id"], "in"))
                    a = self.block(s.body, [(n["id"], "try")])
                    start = [(n["id"], "except")]
                    if s.error_name:
                        start = self.sets_after(
                            [s.error_name], start, lambda x, n=n: (n["id"], "error")
                        )
                    b = self.block(s.handler, start)
                    incoming = a + b
        return incoming

    def out_port(self, n: dict, var: str) -> Port:
        for p in n["outputs"]:
            if p.get("var") == var:
                return (n["id"], p["port"])
        raise KeyError(var)

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
        return self.block(ns.body, incoming)

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
            outs = []
            for p in self.params:
                entry = {"port": p.name, "var": p.name}
                if p.type is not None:
                    entry["type"] = write_type(p.type)
                outs.append(entry)
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
            start = self.sets_after([p.name for p in self.params], start, lambda x: ("inputs", x))
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
        self.edges.sort(
            key=lambda e: (e["to"]["node"], e["to"]["port"], e["from"]["node"], e["from"]["port"])
        )
        g = {"name": self.name, "nodes": self.nodes, "edges": self.edges}
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


def to_graph(program: Program, env: NodeEnv | None = None) -> dict:
    """The graph view of a program."""
    graphs = [_Scope(env, "main", program.body).build()]
    for s in program.body:
        if isinstance(s, Def):
            graphs.append(_Scope(env, s.name, s.body, s.params, s.outputs).build())
    out = {
        "kirgraph": FORMAT,
        "uses": [{"library": u.library, "alias": u.alias} for u in program.uses],
        "graphs": graphs,
    }
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
    return out
