"""Graph view -> text: rebuild KIR text from node graphs (graph.md).

The walk follows control edges. A branch-like node (branch, switch, parallel,
try) gets one namespace per output port; its arms stop at the first node every
arm reaches (the join), and the text continues from there. A labelled merge is
a loop entry: ``()jump(`L`)`` + ``L:``, with edges back into it written as
jumps; when all paths leaving the loop meet at one node, the text continues
there after the namespace.
"""

import math

from kohakunode.errors import KirGraphError
from kohakunode.sig.types import parse_type
from kohakunode.syntax.ast import (
    Arg,
    Assign,
    Branch,
    Call,
    Collect,
    Dataflow,
    Def,
    Each,
    Import,
    Jump,
    Literal,
    Name,
    Namespace,
    Origin,
    OutParam,
    Parallel,
    Param,
    Program,
    Stmt,
    Switch,
    Try,
    TypeHintEntry,
    TypeHints,
    Use,
)


def decode_literal(v):
    if isinstance(v, list):
        return [decode_literal(x) for x in v]
    if isinstance(v, dict):
        if "tuple" in v:
            return tuple(decode_literal(x) for x in v["tuple"])
        if "dict" in v:
            return {k: decode_literal(x) for k, x in v["dict"].items()}
        if "pairs" in v:
            return {decode_literal(k): decode_literal(x) for k, x in v["pairs"]}
        raise KirGraphError(f"bad literal {v!r}")
    return _finite(v)


def _finite(v):
    """``v`` itself, after checking that no float in it is infinite or NaN."""
    if isinstance(v, float) and not math.isfinite(v):
        raise KirGraphError(f"{v} has no KIR literal")
    if isinstance(v, (list, tuple)):
        for x in v:
            _finite(x)
    elif isinstance(v, dict):
        for x in v.values():
            _finite(x)
    return v


def _meta_value(v):
    """A `@meta` value: a JSON list is a tuple (positions, sizes)."""
    return _finite(tuple(v) if isinstance(v, list) else v)


def _origin(value) -> Origin | None:
    """Decode structured provenance independently of the editor metadata switch."""
    if value is None:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(value.get(key), str) for key in ("module", "node_id")
    ):
        raise KirGraphError("origin requires string module and node_id")
    if value.get("line") is not None and type(value["line"]) is not int:
        raise KirGraphError("origin line must be an integer or null")
    for key in ("definition", "generated"):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise KirGraphError(f"origin {key} must be a string or null")
    calls = value.get("calls", [])
    if not isinstance(calls, (list, tuple)) or any(call is None for call in calls):
        raise KirGraphError("origin calls must be a sequence of origins")
    return Origin(
        value["module"],
        value["node_id"],
        value.get("line"),
        value.get("definition"),
        tuple(_origin(call) for call in calls),
        value.get("generated"),
    )


class _Graph:
    def __init__(self, g: dict, with_meta: bool):
        self.g = g
        self.with_meta = with_meta
        self.nodes = {n["id"]: n for n in g["nodes"]}
        self.order = [n["id"] for n in g["nodes"]]
        self.ctrl_out: dict[tuple[str, str], tuple[str, str, Origin | None]] = {}
        self.ctrl_in: dict[str, list[tuple[str, str]]] = {nid: [] for nid in self.nodes}
        self.data_in: dict[tuple[str, str], tuple[str, str]] = {}
        for e in g["edges"]:
            src = (e["from"]["node"], e["from"]["port"])
            dst = (e["to"]["node"], e["to"]["port"])
            if src[0] not in self.nodes or dst[0] not in self.nodes:
                raise KirGraphError(f"edge {e} names an unknown node")
            if e["kind"] == "ctrl":
                self.ctrl_out[src] = (*dst, _origin(e.get("origin")))
                self.ctrl_in[dst[0]].append(src)
            else:
                if dst in self.data_in:
                    raise KirGraphError(f"input {dst} has two data edges")
                self.data_in[dst] = src
        # A `set` variable node names the output port wired into it.
        self.rename: dict[tuple[str, str], str] = {}
        for n in g["nodes"]:
            if n["kind"] == "set":
                src = self.data_in.get((n["id"], "value"))
                if src is None:
                    continue
                if src in self.rename and self.rename[src] != n["props"]["name"]:
                    raise KirGraphError(
                        f"output {src} feeds two variables: {self.rename[src]!r} and "
                        f"{n['props']['name']!r}"
                    )
                self.rename[src] = n["props"]["name"]
        self.members = {
            m for n in g["nodes"] if n["kind"] == "dataflow" for m in n["props"]["members"]
        }
        self.emitted: set[str] = set()
        # Labelled merges a builtin's port enters under the same label: the builtin writes the
        # namespace, every other edge into the merge is a jump
        self.owned: dict[tuple[str, str], str] = {}
        for n in g["nodes"]:
            if n["kind"] in ("branch", "switch", "parallel"):
                for port, label in n["props"]["labels"].items():
                    dst = self.ctrl_out.get((n["id"], port))
                    m = self.nodes[dst[0]] if dst else None
                    if m and m["kind"] == "merge" and m.get("props", {}).get("label") == label:
                        self.owned[(n["id"], port)] = m["id"]
        self.entered = set(self.owned.values())

    # ------------------------------------------------------------ names
    def var(self, src: tuple[str, str]) -> str:
        if src in self.rename:
            return self.rename[src]
        n = self.nodes[src[0]]
        if n["kind"] in ("get", "join"):
            return n["props"]["name"]
        # A graph's input port is its parameter, whether or not it names a variable
        if n["kind"] == "inputs":
            return src[1]
        for p in n.get("outputs", []):
            if p["port"] == src[1]:
                if p.get("var"):
                    return p["var"]
                break
        return f"{src[0]}_{src[1]}"

    def expr(self, nid: str, port: dict):
        src = self.data_in.get((nid, port["port"]))
        if src is not None:
            producer = self.nodes[src[0]]
            if producer["kind"] == "value":
                return Literal(decode_literal(producer["props"]["value"]))
            return Name(self.var(src))
        if "value" in port:
            return Literal(decode_literal(port["value"]))
        return None

    def decorate(self, s: Stmt, n: dict) -> Stmt:
        if self.with_meta:
            s.meta = {"node_id": n["id"]} | {
                k: _meta_value(v) for k, v in n.get("meta", {}).items()
            }
        s.hint = {k: _finite(v) for k, v in n.get("hints", {}).items()}
        s.origin = _origin(n.get("origin"))
        return s

    def namespace(self, label: str, body: list[Stmt], n: dict, port: str = "out") -> Namespace:
        origin = _origin(n.get("namespace_origins", {}).get(port))
        return Namespace(label, body, origin=origin)

    def own(self, nid: str, port: str) -> str | None:
        """The labelled merge a builtin's port enters as its namespace, if any."""
        return self.owned.get((nid, port))

    def arm(self, nid: str, port: str, label: str, stop: frozenset[str]) -> Namespace:
        """The namespace a builtin's port enters, through its labelled merge when it has one."""
        start = self.next_of(nid, port)
        if start and start[0] == self.own(nid, port) and start[0] not in self.emitted:
            merge = start[0]
            self.emitted.add(merge)
            body = self.chain(self.next_of(merge), stop | {merge})
            return self.namespace(label, body, self.nodes[merge])
        return self.namespace(label, self.chain(start, stop), self.nodes[nid], port)

    # ------------------------------------------------------------ statements
    def simple(self, n: dict) -> Stmt:
        nid = n["id"]
        if n["kind"] == "assign":
            out = n["outputs"][0]
            t = parse_type(out["type"]) if out.get("type") else None
            value = self.expr(nid, n["inputs"][0])
            return self.decorate(
                Assign(self.var((nid, "value")), value if value is not None else Literal(None), t),
                n,
            )
        args = []
        for port in n.get("inputs", []):
            e = self.expr(nid, port)
            if e is None:
                continue
            args.append(Arg(e, port["port"] if port.get("keyword") else None))
        outs: list[str | None] = []
        for p in n.get("outputs", []):
            key = (nid, p["port"])
            if key not in self.rename and "var" in p and p["var"] is None:
                outs.append(None)  # discarded with `_`
            else:
                outs.append(self.var(key))
        return self.decorate(Call(n["name"], args, outs), n)

    def bound(self, nid: str, port: str, default: str | None) -> str | None:
        """The name a builtin's output port binds: its `set` node's, else the props'."""
        return self.rename.get((nid, port), default)

    def next_of(self, nid: str, port: str = "out"):
        return self.ctrl_out.get((nid, port))

    # ------------------------------------------------------------ reachability
    def succ(self, nid: str) -> list[str]:
        n = self.nodes[nid]
        return [
            self.ctrl_out[(nid, p)][0] for p in n.get("ctrl_out", []) if (nid, p) in self.ctrl_out
        ]

    def reach(self, start: str | None, stop: frozenset[str] = frozenset()) -> list[str]:
        """Nodes reachable from ``start`` in breadth-first order; ``stop`` nodes are not passed."""
        if start is None:
            return []
        seen, queue, out = {start}, [start], []
        while queue:
            nid = queue.pop(0)
            out.append(nid)
            if nid in stop:
                continue
            for s in self.succ(nid):
                if s not in seen:
                    seen.add(s)
                    queue.append(s)
        return out

    def join_of(
        self, starts: list[str | None], stop: frozenset[str], own: list[str | None] = ()
    ) -> str | None:
        """The first node every arm reaches inside the current region; None when arms never meet.
        ``own`` is per arm the labelled merge it enters as its namespace: never the join. Any
        other edge into a builtin's labelled merge is a jump the walk does not follow."""
        if not starts or any(s is None for s in starts):
            return None
        own = list(own) or [None] * len(starts)
        stops = [stop | (self.entered - {o}) for o in own]
        sets = [set(self.reach(s, st)) for s, st in zip(starts, stops)]
        for nid in self.reach(starts[0], stops[0]):
            if nid in own:
                continue
            if all(nid in s for s in sets):
                return nid
        return None

    def loop_exit(self, merge: str, stop: frozenset[str]) -> str | None:
        """The single node every path leaving the loop reaches first, if there is one."""
        start = self.next_of(merge)[0] if self.next_of(merge) else None
        body = set(self.reach(start, stop)) - {merge}
        back = {nid for nid in body if nid not in stop and merge in self.reach(nid, stop)}
        exits = set()
        for nid in back:
            for s in self.succ(nid):
                if s != merge and s not in back:
                    exits.add(s)
        return exits.pop() if len(exits) == 1 else None

    # ------------------------------------------------------------ chains
    def chain(self, start, stop: frozenset[str]) -> list[Stmt]:
        out: list[Stmt] = []
        cur = start[0] if start else None
        incoming_origin = start[2] if start and len(start) > 2 else None
        while cur is not None:
            n = self.nodes[cur]
            kind = n["kind"]
            label = n.get("props", {}).get("label") if kind == "merge" else None
            if label and (cur in self.emitted or cur in self.entered):
                # Back to a loop entry, or into a namespace its builtin writes
                out.append(Jump(label, origin=incoming_origin))
                break
            if cur in stop:
                # A shared labelled join is still an explicit jump from this
                # arm, with or without provenance. Keeping it also makes text
                # canonicalization stable after origins are erased by writing.
                if label:
                    out.append(Jump(label, origin=incoming_origin))
                break
            if kind == "merge":
                if not label:
                    nxt = self.next_of(cur)
                    cur = nxt[0] if nxt else None
                    incoming_origin = nxt[2] if nxt and len(nxt) > 2 else None
                    continue
                jump = self.decorate(Jump(label), n)
                if incoming_origin is not None:
                    jump.origin = incoming_origin
                out.append(jump)
                self.emitted.add(cur)
                exit_ = self.loop_exit(cur, stop)
                inner_stop = stop | {cur} | ({exit_} if exit_ else set())
                out.append(self.namespace(label, self.chain(self.next_of(cur), inner_stop), n))
                cur = exit_
                incoming_origin = None
                continue
            if cur in self.emitted:
                break
            self.emitted.add(cur)
            if kind in ("call", "assign"):
                out.append(self.simple(n))
                nxt = self.next_of(cur)
            elif kind == "dataflow":
                out.append(
                    self.decorate(
                        Dataflow([self.simple(self.nodes[m]) for m in n["props"]["members"]]), n
                    )
                )
                nxt = self.next_of(cur)
            elif kind in ("each", "collect"):
                p = n["props"]
                items = self.expr(cur, n["inputs"][0]) or Literal([])
                item = self.bound(cur, "item", p.get("item"))
                index = self.bound(cur, "index", p.get("index"))
                if kind == "collect":
                    value_port = next(
                        (port for port in n["inputs"] if port["port"] == "value"), None
                    )
                    if value_port is None or value_port.get("deferred") != "body_end":
                        raise KirGraphError("collect requires a value input deferred to body_end")
                    value = self.expr(cur, value_port)
                    target = self.bound(cur, "results", p.get("target"))
                    if value is None or not isinstance(target, str) or not target:
                        raise KirGraphError("collect requires a value expression and result target")
                    statement = Collect(
                        items, item, index, p["label"], value, target, bool(p.get("has_index"))
                    )
                else:
                    statement = Each(items, item, index, p["label"], bool(p.get("has_index")))
                out.append(self.decorate(statement, n))
                out.append(
                    self.namespace(
                        p["label"], self.chain(self.next_of(cur, "body"), stop | {cur}), n, "body"
                    )
                )
                nxt = self.next_of(cur, "done")
            elif kind in ("branch", "switch", "parallel", "try"):
                ports = n["ctrl_out"]
                starts = [self.next_of(cur, p) for p in ports]
                join = self.join_of(
                    [s[0] if s else None for s in starts], stop, [self.own(cur, p) for p in ports]
                )
                arm_stop = stop | ({join} if join else set())
                if kind == "branch":
                    labels = n["props"]["labels"]
                    cond = self.expr(cur, n["inputs"][0])
                    out.append(self.decorate(Branch(cond, labels["true"], labels["false"]), n))
                    for port in ("true", "false"):
                        out.append(self.arm(cur, port, labels[port], arm_stop))
                elif kind == "switch":
                    labels = n["props"]["labels"]
                    cases = [
                        (decode_literal(v), labels[f"case_{i}"])
                        for i, v in enumerate(n["props"]["cases"])
                    ]
                    value = self.expr(cur, n["inputs"][0])
                    out.append(self.decorate(Switch(value, cases, labels.get("default")), n))
                    for port in ports:
                        out.append(self.arm(cur, port, labels[port], arm_stop))
                elif kind == "parallel":
                    labels = n["props"]["labels"]
                    out.append(self.decorate(Parallel([labels[p] for p in ports]), n))
                    for port in ports:
                        out.append(self.arm(cur, port, labels[port], arm_stop))
                else:
                    err = self.bound(cur, "error", n["props"].get("error_name"))
                    body = self.chain(self.next_of(cur, "try"), arm_stop)
                    handler = self.chain(self.next_of(cur, "except"), arm_stop)
                    out.append(self.decorate(Try(body, handler, err), n))
                nxt = (join, "in") if join else None
            elif kind in ("inputs",):
                nxt = self.next_of(cur)
            elif kind == "join":
                # Where a value is decided: no statement of its own, the flow runs through
                nxt = self.next_of(cur) if n.get("ctrl_out") else None
            elif kind in ("outputs", "get", "set", "value"):
                nxt = None
            else:
                raise KirGraphError(f"unknown node kind {kind!r}")
            cur = nxt[0] if nxt else None
            incoming_origin = nxt[2] if nxt and len(nxt) > 2 else None
        return out

    def body(self) -> list[Stmt]:
        free = [
            nid
            for nid in self.order
            if self.nodes[nid]["kind"] in ("call", "assign")
            and not self.nodes[nid].get("ctrl_in")
            and nid not in self.members
        ]
        out: list[Stmt] = []
        if free:
            out.append(Dataflow([self.simple(self.nodes[nid]) for nid in free]))
            self.emitted.update(free)
        for nid in self.order:
            n = self.nodes[nid]
            if nid in self.emitted or nid in self.members or nid in free:
                continue
            if n["kind"] in ("get", "set", "value", "outputs", "join"):
                continue
            # Loop back edges do not disqualify a root. An unconnected primary
            # input identifies it; an explicit entry marker below determines
            # whether a labelled merge is entered or only declares a namespace.
            source_entry = (
                n["kind"] in ("each", "collect", "merge")
                and n.get("ctrl_in")
                and not any(dst[:2] == (nid, n["ctrl_in"][0]) for dst in self.ctrl_out.values())
            )
            if self.ctrl_in[nid] and n["kind"] != "inputs" and not source_entry:
                continue
            if n["kind"] == "merge" and not n.get("props", {}).get("label"):
                continue
            if n["kind"] == "merge" and n.get("entry") is not True:
                # Never infer execution from provenance. Legacy graphs without
                # the entry marker conservatively describe an unentered namespace.
                self.emitted.add(nid)
                out.append(
                    self.namespace(
                        n["props"]["label"], self.chain(self.next_of(nid), frozenset({nid})), n
                    )
                )
                continue
            out.extend(self.chain((nid, "in"), frozenset()))
        return out


def from_graph(graph: dict, with_meta: bool = True) -> Program:
    """The canonical text of a graph view, as a program."""
    # Version 3 adds node paths and regions, which the text never needs
    if graph.get("kirgraph") not in (2, 3):
        raise KirGraphError(f"unsupported kirgraph version {graph.get('kirgraph')!r}")
    program = Program(
        uses=[Use(u["library"], u.get("alias")) for u in graph.get("uses", [])],
        mode=graph.get("mode"),
        imports=[Import(imp["module"], imp["alias"]) for imp in graph.get("imports", [])],
        exports=list(graph.get("exports", [])),
    )
    hints = graph.get("typehints")
    if hints or graph.get("typehint_groups"):
        entries = [
            TypeHintEntry(
                h["name"],
                tuple(parse_type(t) for t in h["inputs"]),
                tuple(parse_type(t) for t in h["outputs"]),
            )
            for h in hints or []
        ]
        groups = graph.get("typehint_groups", [{"count": len(entries)}])
        offset = 0
        for group in groups:
            count = group.get("count")
            if type(count) is not int or count < 0 or offset + count > len(entries):
                raise KirGraphError("invalid typehint group count")
            program.body.append(
                TypeHints(entries[offset : offset + count], origin=_origin(group.get("origin")))
            )
            offset += count
        if offset != len(entries):
            raise KirGraphError("typehint groups do not cover all entries")
    main = None
    for g in graph["graphs"]:
        if g["name"] == "main":
            main = g
            continue
        rebuilt = _Graph(g, with_meta)
        body = rebuilt.body()
        out_node = rebuilt.nodes.get("outputs")
        for o in g.get("outputs", []):
            src = rebuilt.data_in.get(("outputs", o["name"]))
            if out_node is not None and src is not None and rebuilt.var(src) != o["name"]:
                body.append(Assign(o["name"], Name(rebuilt.var(src))))
        params = [
            Param(
                p["name"],
                parse_type(p["type"]) if p.get("type") else None,
                Literal(decode_literal(p["default"])) if "default" in p else None,
            )
            for p in g.get("params", [])
        ]
        outputs = [
            OutParam(o["name"], parse_type(o["type"]) if o.get("type") else None)
            for o in g.get("outputs", [])
        ]
        program.body.append(Def(g["name"], params, outputs, body, origin=_origin(g.get("origin"))))
    if main is not None:
        program.body.extend(_Graph(main, with_meta).body())
    return program
