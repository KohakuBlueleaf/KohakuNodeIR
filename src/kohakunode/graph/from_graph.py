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
    Dataflow,
    Def,
    Each,
    Jump,
    Literal,
    Name,
    Namespace,
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


class _Graph:
    def __init__(self, g: dict, with_meta: bool):
        self.g = g
        self.with_meta = with_meta
        self.nodes = {n["id"]: n for n in g["nodes"]}
        self.order = [n["id"] for n in g["nodes"]]
        self.ctrl_out: dict[tuple[str, str], tuple[str, str]] = {}
        self.ctrl_in: dict[str, list[tuple[str, str]]] = {nid: [] for nid in self.nodes}
        self.data_in: dict[tuple[str, str], tuple[str, str]] = {}
        for e in g["edges"]:
            src = (e["from"]["node"], e["from"]["port"])
            dst = (e["to"]["node"], e["to"]["port"])
            if src[0] not in self.nodes or dst[0] not in self.nodes:
                raise KirGraphError(f"edge {e} names an unknown node")
            if e["kind"] == "ctrl":
                self.ctrl_out[src] = dst
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

    # ------------------------------------------------------------ names
    def var(self, src: tuple[str, str]) -> str:
        if src in self.rename:
            return self.rename[src]
        n = self.nodes[src[0]]
        if n["kind"] == "get":
            return n["props"]["name"]
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
        return s

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

    def join_of(self, starts: list[str | None], stop: frozenset[str]) -> str | None:
        """The first node every arm reaches inside the current region; None when arms never meet."""
        if not starts or any(s is None for s in starts):
            return None
        sets = [set(self.reach(s, stop)) for s in starts]
        for nid in self.reach(starts[0], stop):
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
        while cur is not None:
            n = self.nodes[cur]
            kind = n["kind"]
            label = n.get("props", {}).get("label") if kind == "merge" else None
            if label and cur in self.emitted:
                out.append(Jump(label))  # back to a loop entry already written
                break
            if cur in stop:
                break
            if kind == "merge":
                if not label:
                    nxt = self.next_of(cur)
                    cur = nxt[0] if nxt else None
                    continue
                out.append(self.decorate(Jump(label), n))
                self.emitted.add(cur)
                exit_ = self.loop_exit(cur, stop)
                inner_stop = stop | {cur} | ({exit_} if exit_ else set())
                out.append(Namespace(label, self.chain(self.next_of(cur), inner_stop)))
                cur = exit_
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
            elif kind == "each":
                p = n["props"]
                items = self.expr(cur, n["inputs"][0]) or Literal([])
                item = self.bound(cur, "item", p.get("item"))
                index = self.bound(cur, "index", p.get("index"))
                out.append(
                    self.decorate(Each(items, item, index, p["label"], bool(p.get("has_index"))), n)
                )
                out.append(
                    Namespace(p["label"], self.chain(self.next_of(cur, "body"), stop | {cur}))
                )
                nxt = self.next_of(cur, "done")
            elif kind in ("branch", "switch", "parallel", "try"):
                ports = n["ctrl_out"]
                starts = [self.next_of(cur, p) for p in ports]
                join = self.join_of([s[0] if s else None for s in starts], stop)
                arm_stop = stop | ({join} if join else set())
                if kind == "branch":
                    labels = n["props"]["labels"]
                    cond = self.expr(cur, n["inputs"][0])
                    out.append(self.decorate(Branch(cond, labels["true"], labels["false"]), n))
                    for port in ("true", "false"):
                        out.append(
                            Namespace(labels[port], self.chain(self.next_of(cur, port), arm_stop))
                        )
                elif kind == "switch":
                    labels = n["props"]["labels"]
                    cases = [
                        (decode_literal(v), labels[f"case_{i}"])
                        for i, v in enumerate(n["props"]["cases"])
                    ]
                    value = self.expr(cur, n["inputs"][0])
                    out.append(self.decorate(Switch(value, cases, labels.get("default")), n))
                    for port in ports:
                        out.append(
                            Namespace(labels[port], self.chain(self.next_of(cur, port), arm_stop))
                        )
                elif kind == "parallel":
                    labels = n["props"]["labels"]
                    out.append(self.decorate(Parallel([labels[p] for p in ports]), n))
                    for port in ports:
                        out.append(
                            Namespace(labels[port], self.chain(self.next_of(cur, port), arm_stop))
                        )
                else:
                    err = self.bound(cur, "error", n["props"].get("error_name"))
                    body = self.chain(self.next_of(cur, "try"), arm_stop)
                    handler = self.chain(self.next_of(cur, "except"), arm_stop)
                    out.append(self.decorate(Try(body, handler, err), n))
                nxt = (join, "in") if join else None
            elif kind in ("inputs",):
                nxt = self.next_of(cur)
            elif kind in ("outputs", "get", "set", "value"):
                nxt = None
            else:
                raise KirGraphError(f"unknown node kind {kind!r}")
            cur = nxt[0] if nxt else None
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
            if n["kind"] in ("get", "set", "value", "outputs"):
                continue
            if self.ctrl_in[nid] and n["kind"] != "inputs":
                continue
            if n["kind"] == "merge" and not n.get("props", {}).get("label"):
                continue
            if n["kind"] == "merge":
                # A labelled merge nothing enters: a namespace never entered.
                self.emitted.add(nid)
                out.append(
                    Namespace(n["props"]["label"], self.chain(self.next_of(nid), frozenset({nid})))
                )
                continue
            out.extend(self.chain((nid, "in"), frozenset()))
        return out


def from_graph(graph: dict, with_meta: bool = True) -> Program:
    """The canonical text of a graph view, as a program."""
    if graph.get("kirgraph") != 2:
        raise KirGraphError(f"unsupported kirgraph version {graph.get('kirgraph')!r}")
    program = Program(
        uses=[Use(u["library"], u.get("alias")) for u in graph.get("uses", [])],
        mode=graph.get("mode"),
    )
    hints = graph.get("typehints")
    if hints:
        program.body.append(
            TypeHints(
                [
                    TypeHintEntry(
                        h["name"],
                        tuple(parse_type(t) for t in h["inputs"]),
                        tuple(parse_type(t) for t in h["outputs"]),
                    )
                    for h in hints
                ]
            )
        )
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
        program.body.append(Def(g["name"], params, outputs, body))
    if main is not None:
        program.body.extend(_Graph(main, with_meta).body())
    return program
