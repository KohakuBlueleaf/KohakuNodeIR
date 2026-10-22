"""The checker: every rule of checks.md."""

import copy
from dataclasses import dataclass

from kohakunode.flow.cfg import UNDEF, build_cfg, defs_of, reaching
from kohakunode.flow.order import DataflowCycle, is_simple, sort_dataflow
from kohakunode.sig.env import NodeEnv, Resolved
from kohakunode.sig.types import fits, literal_type, type_text
from kohakunode.syntax.ast import (
    ANY,
    Assign,
    Branch,
    Call,
    Dataflow,
    Def,
    Each,
    Jump,
    Literal,
    Namespace,
    Parallel,
    Program,
    Stmt,
    Switch,
    Try,
    TypeExpr,
    labels_entered,
    reads,
    walk,
    writes,
)

CONTROL = (Branch, Switch, Jump, Parallel, Each, Namespace, Try)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    line: int | None = None

    @property
    def severity(self) -> str:
        return "error" if self.code.startswith("E") else "warning"

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line is not None else ""
        return f"{where}{self.code} {self.message}"


class _Checker:
    def __init__(self, env: NodeEnv):
        self.env = env
        self.out: list[Diagnostic] = []

    def add(self, code: str, message: str, s: Stmt | None = None) -> None:
        if s is not None and s.origin is not None and s.origin.module != "<text>":
            context = s.origin.module
            if s.origin.definition is not None:
                context += f"::{s.origin.definition}"
            message = f"{context}: {message}"
        self.out.append(Diagnostic(code, message, s.line if s is not None else None))

    # ------------------------------------------------------------ whole program
    def program(self, p: Program) -> None:
        self.reserved(p)
        if p.mode == "dataflow":
            for s in walk(p.body):
                if isinstance(s, CONTROL):
                    self.add("E060", "@mode dataflow file contains control flow", s)
                    break
        for s in walk(p.body):
            if isinstance(s, Dataflow):
                for inner in s.body:
                    if not is_simple(inner):
                        self.add("E061", "@dataflow blocks hold only assignments and calls", inner)
        try:
            sort_dataflow(p, self.is_ordered)
        except DataflowCycle as exc:
            self.add("E033", "dependency cycle in @dataflow block", exc.stmts[0])
            return
        self.recursion(p)
        self.scope(p.body, (), None)
        for s in walk(p.body):
            if isinstance(s, Def):
                self.scope(s.body, tuple(x.name for x in s.params), s)

    def is_ordered(self, s: Stmt) -> bool:
        if isinstance(s, Call):
            r = self.env.resolve(s.name)
            return isinstance(r, Resolved) and r.signature.ordered
        return False

    def reserved(self, p: Program) -> None:
        for s in walk(p.body):
            names = writes(s) + reads(s) + labels_entered(s)
            if isinstance(s, Namespace):
                names.append(s.label)
            if isinstance(s, Def):
                names += [x.name for x in s.params] + [x.name for x in s.outputs]
            if isinstance(s, Try) and s.error_name:
                names.append(s.error_name)
            for n in names:
                if "__" in n:
                    self.add("E013", f"name or label {n!r} contains '__', which is reserved", s)
            if isinstance(s, Call) and s.name.startswith("kir.") and not self.env.internal:
                self.add("E013", f"node {s.name!r} uses the reserved 'kir.' prefix", s)

    def recursion(self, p: Program) -> None:
        defs = {s.name: s for s in walk(p.body) if isinstance(s, Def)}
        calls = {
            name: {c.name for c in walk(d.body) if isinstance(c, Call) and c.name in defs}
            for name, d in defs.items()
        }
        for start in defs:
            stack, seen = list(calls[start]), set()
            while stack:
                n = stack.pop()
                if n == start:
                    self.add("E050", f"@def {start!r} calls itself", defs[start])
                    break
                if n not in seen:
                    seen.add(n)
                    stack.extend(calls[n])

    # ------------------------------------------------------------ one scope
    def scope(self, body: list[Stmt], params: tuple[str, ...], d: Def | None) -> None:
        local = list(_scope_walk(body))
        types = self.name_types(local, d)
        for s in local:
            if isinstance(s, Call):
                self.call(s, types)
            elif isinstance(s, Branch):
                t = self.expr_type(s.cond, types)
                if t is not None and t.kind != "any" and not fits(t, TypeExpr("name", "bool")):
                    self.add("E041", f"branch condition has type {type_text(t)}, not bool", s)
        g = build_cfg(body, params)
        for s, label in g.problems:
            self.add("E030", f"label `{label}` not found", s)
        namespaces = [s for s in local if isinstance(s, Namespace)]
        for ns in namespaces:
            owners = g.owners.get(id(ns), [])
            non_jump = [o for o in owners if not isinstance(o, Jump)]
            if len(non_jump) > 1:
                self.add("E031", f"namespace `{ns.label}` is entered by more than one builtin", ns)
            if not owners:
                self.add("W001", f"namespace `{ns.label}` is never entered", ns)
            if any(isinstance(o, Each) for o in owners):
                inside = {id(x) for x in walk(ns.body)}
                for o in owners:
                    if isinstance(o, Jump) and id(o) not in inside:
                        self.add("E032", f"jump into the body of each `{ns.label}`", o)
        names = {n for s in local for n in writes(s) + reads(s)} - set(params)
        inn = reaching(g, tuple(sorted(names)))
        reach = g.reachable()
        read_names = set()
        for n in reach:
            node = g.nodes[n]
            for name in node.reads:
                read_names.add(name)
                if UNDEF in defs_of(inn[n], name):
                    self.add("E020", f"{name!r} may be read before it is written", node.stmt)
        if d is not None and g.exit in reach:
            for o in d.outputs:
                if UNDEF in defs_of(inn[g.exit], o.name):
                    self.add(
                        "E021", f"output {o.name!r} of @def {d.name!r} is not set on every path", d
                    )
            read_names |= {o.name for o in d.outputs}
        for s in local:
            if isinstance(s, Parallel):
                self.parallel(s, {ns.label: ns for ns in namespaces})
        if d is not None:  # top-level final values are the job's results
            for s in local:
                for name in writes(s):
                    if name not in read_names:
                        self.add("W020", f"{name!r} is written but never read", s)

    def parallel(self, s: Parallel, table: dict[str, Namespace]) -> None:
        arms = [table[label] for label in s.labels if label in table]
        w = [{n for x in walk(a.body) for n in writes(x)} for a in arms]
        r = [{n for x in walk(a.body) for n in reads(x)} for a in arms]
        for i in range(len(arms)):
            for j in range(len(arms)):
                if i == j:
                    continue
                if i < j and w[i] & w[j]:
                    self.add(
                        "W010",
                        f"parallel arms `{arms[i].label}` and `{arms[j].label}` both write {sorted(w[i] & w[j])}",
                        s,
                    )
                if w[i] & r[j]:
                    self.add(
                        "W010",
                        f"parallel arm `{arms[j].label}` reads {sorted(w[i] & r[j])} written by `{arms[i].label}`",
                        s,
                    )

    # ------------------------------------------------------------ calls and types
    def call(self, s: Call, types: dict[str, TypeExpr]) -> None:
        r = self.env.resolve(s.name)
        if r == "unknown":
            self.add("E010", f"unknown node {s.name!r}", s)
            return
        if r == "reserved":
            return
        if isinstance(r, str):
            self.add("E011", f"node {s.name!r} is {r}", s)
            return
        sig = r.signature
        positional = [a for a in s.args if a.key is None]
        if len(positional) > len(sig.inputs):
            self.add("E012", f"{s.name} takes {len(sig.inputs)} inputs, {len(positional)} given", s)
            return
        bound = {}
        for port, a in zip(sig.inputs, positional):
            bound[port.name] = a.value
        for a in s.args:
            if a.key is None:
                continue
            if sig.input(a.key) is None:
                self.add("E012", f"{s.name} has no input {a.key!r}", s)
            elif a.key in bound:
                self.add("E012", f"{s.name} input {a.key!r} given twice", s)
            else:
                bound[a.key] = a.value
        for port in sig.inputs:
            if port.required and port.name not in bound:
                self.add("E012", f"{s.name} input {port.name!r} is required", s)
        if len(s.outs) != len(sig.outputs):
            self.add("E012", f"{s.name} has {len(sig.outputs)} outputs, {len(s.outs)} bound", s)
        for name, value in bound.items():
            port = sig.input(name)
            t = self.expr_type(value, types)
            if t is not None and not fits(t, port.type):
                self.add(
                    "E040",
                    f"{s.name} input {name!r} expects {type_text(port.type)}, got {type_text(t)}",
                    s,
                )

    def expr_type(self, e, types: dict[str, TypeExpr]) -> TypeExpr | None:
        if isinstance(e, Literal):
            return literal_type(e.value)
        return types.get(e.id)

    def name_types(self, local: list[Stmt], d: Def | None) -> dict[str, TypeExpr]:
        """A name's type when every write of it in the scope agrees on one known type."""
        seen: dict[str, set[TypeExpr]] = {}

        def note(name, t):
            seen.setdefault(name, set()).add(t if t is not None else ANY)

        if d is not None:
            for p in d.params:
                note(p.name, p.type)
        for s in local:
            if isinstance(s, Assign):
                note(
                    s.target,
                    s.type
                    or (literal_type(s.value.value) if isinstance(s.value, Literal) else None),
                )
            elif isinstance(s, Call):
                r = self.env.resolve(s.name)
                outs = r.signature.outputs if isinstance(r, Resolved) else ()
                for i, o in enumerate(s.outs):
                    if o is not None:
                        note(o, outs[i].type if i < len(outs) else None)
            elif isinstance(s, Each):
                for n in (s.item, s.index):
                    if n is not None:
                        note(n, None)
            elif isinstance(s, Try) and s.error_name:
                note(s.error_name, TypeExpr("name", "dict"))
        return {n: next(iter(ts)) for n, ts in seen.items() if len(ts) == 1 and ANY not in ts}


def _scope_walk(stmts: list[Stmt]):
    """Statements of one scope: like walk(), but not into `@def` bodies."""
    for s in stmts:
        if isinstance(s, Def):
            continue
        yield s
        match s:
            case Namespace() | Dataflow():
                yield from _scope_walk(s.body)
            case Try():
                yield from _scope_walk(s.body)
                yield from _scope_walk(s.handler)


def check(program: Program, env: NodeEnv) -> list[Diagnostic]:
    """All diagnostics for a program, errors and warnings, in source order."""
    c = _Checker(env)
    c.program(copy.deepcopy(program))
    return sorted(set(c.out), key=lambda d: (d.line or 0, d.code, d.message))
