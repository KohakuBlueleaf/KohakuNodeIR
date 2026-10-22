"""The ``inline`` pass: every `@def` call becomes a renamed copy of its body (passes.md)."""

import copy

from kohakunode.origins import derive_origin
from kohakunode.syntax.ast import (
    Arg,
    Assign,
    Branch,
    Call,
    Collect,
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
    children,
    walk,
)


def _rename_expr(e, f):
    return Name(f(e.id)) if isinstance(e, Name) else e


def rename(stmts: list[Stmt], f) -> None:
    """Rename every name and label in place with ``f``."""
    for s in stmts:
        match s:
            case Assign():
                s.target = f(s.target)
                s.value = _rename_expr(s.value, f)
            case Call():
                s.args = [Arg(_rename_expr(a.value, f), a.key) for a in s.args]
                s.outs = [f(o) if o is not None else None for o in s.outs]
            case Branch():
                s.cond = _rename_expr(s.cond, f)
                s.true_label, s.false_label = f(s.true_label), f(s.false_label)
            case Switch():
                s.value = _rename_expr(s.value, f)
                s.cases = [(v, f(label)) for v, label in s.cases]
                s.default = f(s.default) if s.default else None
            case Jump():
                s.label = f(s.label)
            case Parallel():
                s.labels = [f(x) for x in s.labels]
            case Each() | Collect():
                s.items = _rename_expr(s.items, f)
                s.item = f(s.item) if s.item else None
                s.index = f(s.index) if s.index else None
                s.label = f(s.label)
                if isinstance(s, Collect):
                    s.value = _rename_expr(s.value, f)
                    s.target = f(s.target)
            case Namespace():
                s.label = f(s.label)
            case Try():
                s.error_name = f(s.error_name) if s.error_name else None
        for body in children(s):
            rename(body, f)


class Inliner:
    """Inline the `@def`s of ``program`` (its own, already sorted, copies)."""

    def __init__(self, program: Program):
        self.defs = {s.name: s for s in walk(program.body) if isinstance(s, Def)}
        self.counter: dict[str, int] = {}

    def block(self, stmts: list[Stmt]) -> list[Stmt]:
        out: list[Stmt] = []
        for s in stmts:
            if isinstance(s, Def):
                continue
            if isinstance(s, Call) and s.name in self.defs:
                out.extend(self.expand(s, self.defs[s.name]))
                continue
            for body in children(s):
                body[:] = self.block(body)
            out.append(s)
        return out

    def expand(self, call: Call, d: Def) -> list[Stmt]:
        k = self.counter.get(d.name, 0) + 1
        self.counter[d.name] = k
        prefix = f"{d.name}__{k}__"

        def f(x: str) -> str:
            return prefix + x

        positional = [a for a in call.args if a.key is None]
        given = {p.name: a.value for p, a in zip(d.params, positional)}
        given |= {a.key: a.value for a in call.args if a.key is not None}
        out: list[Stmt] = []
        for p in d.params:
            value = given.get(p.name, p.default if p.default is not None else Literal(None))
            out.append(
                Assign(
                    f(p.name),
                    value,
                    line=call.line,
                    origin=derive_origin(call.origin or d.origin, generated="inline.arg"),
                )
            )
        body = copy.deepcopy(d.body)
        if call.origin is not None:
            ancestry = call.origin.calls + (call.origin,)
            for stmt in walk(body):
                stmt.origin = derive_origin(stmt.origin, calls=ancestry)
        rename(body, f)
        out.extend(self.block(body))
        for o, target in zip(d.outputs, call.outs):
            if target is not None:
                out.append(
                    Assign(
                        target,
                        Name(f(o.name)),
                        line=call.line,
                        origin=derive_origin(call.origin or d.origin, generated="inline.output"),
                    )
                )
        if out:
            out[0].hint = call.hint | out[0].hint
        return out
