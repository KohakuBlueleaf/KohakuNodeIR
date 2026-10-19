"""The ``expand_each`` pass: ``each`` as a loop of v1 constructs (passes.md)."""

from kohakunode.syntax.ast import (
    Arg,
    Assign,
    Branch,
    Call,
    Each,
    Jump,
    Literal,
    Name,
    Namespace,
    Stmt,
    children,
)


class EachExpander:
    def __init__(self) -> None:
        self.k = 0

    def block(self, stmts: list[Stmt]) -> list[Stmt]:
        bodies = {s.label: s for s in stmts if isinstance(s, Namespace)}
        owned = {s.label for s in stmts if isinstance(s, Each)}
        out: list[Stmt] = []
        for s in stmts:
            if isinstance(s, Namespace) and s.label in owned:
                continue
            if isinstance(s, Each):
                out.extend(self.expand(s, bodies.get(s.label)))
                continue
            for body in children(s):
                body[:] = self.block(body)
            out.append(s)
        return out

    def expand(self, s: Each, ns: Namespace | None) -> list[Stmt]:
        self.k += 1
        p = f"each__{self.k}__"
        loop, done = f"each__{self.k}", f"each__{self.k}__done"
        items, index, item, more = p + "items", p + "index", p + "item", p + "more"
        body: list[Stmt] = []
        if s.item is not None:
            body.append(Assign(s.item, Name(item), line=s.line))
        if s.index is not None:
            body.append(Assign(s.index, Name(index), line=s.line))
        body.extend(self.block(ns.body) if ns is not None else [])
        body.append(Call("kir.next_index", [Arg(Name(index))], [index], line=s.line))
        body.append(Jump(loop, line=s.line))
        header = [
            Call("kir.item_at", [Arg(Name(items)), Arg(Name(index))], [item, more], line=s.line),
            Branch(Name(more), s.label, done, line=s.line),
            Namespace(s.label, body, line=ns.line if ns is not None else s.line),
            Namespace(done, [], line=s.line),
        ]
        return [
            Call("kir.to_list", [Arg(s.items)], [items], hint=s.hint, line=s.line),
            Assign(index, Literal(0), line=s.line),
            Jump(loop, line=s.line),
            Namespace(loop, header, line=s.line),
        ]
