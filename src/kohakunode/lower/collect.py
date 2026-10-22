"""Correctness baseline: collect as private list accumulation around an each loop.

The accumulator is unpublished until normal completion. ``kir.collect_append``
uses standard fresh-list append semantics; the direct interpreter instead keeps
one private list and appends in place. Both retain references to yielded values.
"""

from kohakunode.origins import derive_origin
from kohakunode.syntax.ast import (
    Arg,
    Assign,
    Call,
    Collect,
    Def,
    Each,
    Literal,
    Name,
    Namespace,
    Program,
    Stmt,
    Try,
    children,
    deferred_reads,
    reads,
    walk,
    writes,
)


class CollectExpander:
    def __init__(self, program: Program) -> None:
        self.counter = 0
        self.used = set()
        for stmt in walk(program.body):
            self.used.update(reads(stmt))
            self.used.update(deferred_reads(stmt))
            self.used.update(writes(stmt))
            if isinstance(stmt, Def):
                self.used.update(param.name for param in stmt.params)
                self.used.update(port.name for port in stmt.outputs)
            elif isinstance(stmt, Try) and stmt.error_name is not None:
                self.used.add(stmt.error_name)

    def fresh(self) -> tuple[str, str]:
        while True:
            self.counter += 1
            values = f"collect__{self.counter}__values"
            items = f"collect__{self.counter}__items"
            if not {values, items} & self.used:
                self.used.update((values, items))
                return values, items

    def block(self, stmts: list[Stmt]) -> list[Stmt]:
        namespaces = {stmt.label: stmt for stmt in stmts if isinstance(stmt, Namespace)}
        out: list[Stmt] = []
        # Prepare every owned body before descending, including namespaces which
        # are textually before their owner. The checker guarantees one owner.
        for stmt in stmts:
            if not isinstance(stmt, Collect):
                out.append(stmt)
                continue
            namespace = namespaces.get(stmt.label)
            if namespace is None:
                raise ValueError(f"collect namespace {stmt.label!r} not found")
            accumulator, items = self.fresh()
            namespace.body.append(
                Call(
                    "kir.collect_append",
                    [Arg(Name(accumulator)), Arg(stmt.value)],
                    [accumulator],
                    line=stmt.line,
                    origin=derive_origin(stmt.origin, generated="collect.append"),
                )
            )
            out.extend(
                [
                    Call(
                        "kir.collect_items",
                        [Arg(stmt.items)],
                        [items],
                        line=stmt.line,
                        origin=derive_origin(stmt.origin, generated="collect.items"),
                    ),
                    Assign(
                        accumulator,
                        Literal([]),
                        line=stmt.line,
                        origin=derive_origin(stmt.origin, generated="collect.init"),
                    ),
                    Each(
                        Name(items),
                        stmt.item,
                        stmt.index,
                        stmt.label,
                        stmt.has_index,
                        meta=stmt.meta,
                        hint=stmt.hint,
                        line=stmt.line,
                        origin=stmt.origin,
                    ),
                    Assign(
                        stmt.target,
                        Name(accumulator),
                        line=stmt.line,
                        origin=derive_origin(stmt.origin, generated="collect.result"),
                    ),
                ]
            )
        for stmt in out:
            for body in children(stmt):
                body[:] = self.block(body)
        return out
