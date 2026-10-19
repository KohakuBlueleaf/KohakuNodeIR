"""Control-flow graph of one scope, and reaching definitions over it.

Nodes are simple statements (assignments, calls, builtins) plus synthetic
``entry``, ``exit`` and ``bind`` nodes. A ``bind`` node sits at the start of an
``each`` body and writes the item and index names. Edges carry a kind:
``flow`` or ``exc`` (from a statement inside a `@try` body to the handler,
taken *before* the statement's writes).

`@def` bodies are separate scopes and are not entered.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from kohakunode.syntax.ast import (
    Branch,
    Dataflow,
    Def,
    Each,
    Jump,
    Namespace,
    Parallel,
    Stmt,
    Switch,
    Try,
    TypeHints,
    reads,
    writes,
)

UNDEF = -1  # pseudo definition: "not written on this path"


@dataclass
class CNode:
    kind: str  # "stmt", "entry", "exit", "bind"
    stmt: Stmt | None = None
    writes: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()


@dataclass
class CFG:
    nodes: list[CNode] = field(default_factory=list)
    succ: list[list[tuple[int, str]]] = field(default_factory=list)
    entry: int = 0
    exit: int = 1
    node_of: dict[int, int] = field(default_factory=dict)  # id(stmt) -> node
    problems: list[tuple[Stmt, str]] = field(default_factory=list)  # unresolved labels
    owners: dict[int, list[Stmt]] = field(
        default_factory=dict
    )  # id(namespace) -> entering builtins
    binds: dict[int, int] = field(default_factory=dict)  # id(Each or Try) -> its bind node

    def preds(self) -> list[list[tuple[int, str]]]:
        p: list[list[tuple[int, str]]] = [[] for _ in self.nodes]
        for a, outs in enumerate(self.succ):
            for b, kind in outs:
                p[b].append((a, kind))
        return p

    def reachable(self) -> set[int]:
        seen, stack = {self.entry}, [self.entry]
        while stack:
            for b, _ in self.succ[stack.pop()]:
                if b not in seen:
                    seen.add(b)
                    stack.append(b)
        return seen


Target = Callable[[], int]


class _Builder:
    def __init__(self) -> None:
        self.g = CFG()
        self.pending: list[Callable[[], None]] = []
        self.ns_entry: dict[int, Target] = {}

    def new(self, kind: str, stmt: Stmt | None = None, w=(), r=()) -> int:
        self.g.nodes.append(CNode(kind, stmt, tuple(w), tuple(r)))
        self.g.succ.append([])
        n = len(self.g.nodes) - 1
        if stmt is not None:
            self.g.node_of[id(stmt)] = n
        return n

    def edge_later(self, a: int, target: Target, kind: str = "flow") -> None:
        self.pending.append(lambda: self.g.succ[a].append((target(), kind)))

    def ns_target(self, ns: Namespace) -> Target:
        return lambda: self.ns_entry[id(ns)]()

    def block(self, stmts: list[Stmt], scopes: list[dict[str, Namespace]], cont: Target) -> Target:
        """Build a block; return a target for its first statement."""
        local = {s.label: s for s in stmts if isinstance(s, Namespace)}
        chain = [local, *scopes]
        after: list[Target] = [cont] * (len(stmts) + 1)
        nodes: dict[int, int] = {}
        for i in range(len(stmts) - 1, -1, -1):
            s = stmts[i]
            nxt = after[i + 1]
            if isinstance(s, (Namespace, Def, TypeHints)):
                after[i] = nxt
            elif isinstance(s, Dataflow):
                after[i] = self.block(s.body, chain, nxt)
            elif isinstance(s, Try):
                start = len(self.g.nodes)
                body_entry = self.block(s.body, chain, nxt)
                end = len(self.g.nodes)
                handler_entry = self.block(s.handler, chain, nxt)
                if s.error_name:
                    bind = self.new("bind", None, (s.error_name,))
                    self.g.binds[id(s)] = bind
                    self.edge_later(bind, handler_entry)
                    handler_entry = lambda bind=bind: bind  # noqa: E731
                for n in range(start, end):
                    if self.g.nodes[n].kind == "stmt":
                        self.edge_later(n, handler_entry, "exc")
                after[i] = body_entry
            else:
                n = self.new("stmt", s, writes(s) if not isinstance(s, Each) else (), reads(s))
                nodes[i] = n
                after[i] = lambda n=n: n
        # Namespace bodies: continuation depends on the builtin that owns them.
        cont_of: dict[int, Target] = {}
        for i, s in enumerate(stmts):
            if i not in nodes:
                continue
            match s:
                case Parallel():
                    arms = [local.get(label) for label in s.labels]
                    for k, ns in enumerate(arms):
                        if ns is None:
                            continue
                        if k + 1 < len(arms) and arms[k + 1] is not None:
                            cont_of[id(ns)] = self.ns_target(arms[k + 1])
                        else:
                            cont_of[id(ns)] = after[i + 1]
                case Each():
                    ns = local.get(s.label)
                    if ns is not None:
                        cont_of[id(ns)] = lambda n=nodes[i]: n
        for i, s in enumerate(stmts):
            if isinstance(s, Namespace):
                cont_ns = cont_of.get(id(s), after[i + 1])
                self.ns_entry[id(s)] = self.block(s.body, chain, cont_ns)
        for i, n in nodes.items():
            self.wire(stmts[i], n, chain, local, after[i + 1])
        return after[0]

    def wire(self, s: Stmt, n: int, chain, local, nxt: Target) -> None:
        def enter(label: str, scopes) -> Target | None:
            for table in scopes:
                if label in table:
                    self.g.owners.setdefault(id(table[label]), []).append(s)
                    return self.ns_target(table[label])
            self.g.problems.append((s, label))
            return None

        match s:
            case Branch() | Switch():
                labels = (
                    [s.true_label, s.false_label]
                    if isinstance(s, Branch)
                    else [label for _, label in s.cases] + ([s.default] if s.default else [])
                )
                for label in labels:
                    t = enter(label, [local])
                    if t is not None:
                        self.edge_later(n, t)
            case Parallel():
                # Arms run one after another (their continuations chain); enter the first.
                targets = [enter(label, [local]) for label in s.labels]
                if targets[0] is not None:
                    self.edge_later(n, targets[0])
            case Jump():
                t = enter(s.label, chain)
                if t is not None:
                    self.edge_later(n, t)
            case Each():
                t = enter(s.label, [local])
                if t is not None:
                    names = [x for x in (s.item, s.index) if x is not None]
                    bind = self.new("bind", None, names)
                    self.g.binds[id(s)] = bind
                    self.g.succ[n].append((bind, "flow"))
                    self.edge_later(bind, t)
                self.edge_later(n, nxt)
            case _:
                self.edge_later(n, nxt)


def build_cfg(body: list[Stmt], params: tuple[str, ...] = ()) -> CFG:
    b = _Builder()
    entry = b.new("entry", None, params)
    exit_ = b.new("exit")
    first = b.block(body, [], lambda: exit_)
    b.edge_later(entry, first)
    for p in b.pending:
        p()
    b.g.entry, b.g.exit = entry, exit_
    return b.g


def reaching(g: CFG, undefined: tuple[str, ...] = ()) -> list[frozenset]:
    """IN set of every node: pairs ``(name, defining node)``; ``UNDEF`` marks a path with no write.

    ``undefined`` names start as ``UNDEF`` at the entry.
    """
    preds = g.preds()
    out: list[frozenset] = [frozenset() for _ in g.nodes]
    inn: list[frozenset] = [frozenset() for _ in g.nodes]
    start = frozenset((x, UNDEF) for x in undefined)
    order = sorted(g.reachable())
    changed = True
    while changed:
        changed = False
        for n in order:
            acc = set(start) if n == g.entry else set()
            for p, kind in preds[n]:
                acc |= inn[p] if kind == "exc" else out[p]
            new_in = frozenset(acc)
            w = g.nodes[n].writes
            new_out = frozenset({d for d in new_in if d[0] not in w} | {(x, n) for x in w})
            if new_in != inn[n] or new_out != out[n]:
                inn[n], out[n] = new_in, new_out
                changed = True
    return inn


def defs_of(inn: frozenset, name: str) -> set[int]:
    return {d for x, d in inn if x == name}
