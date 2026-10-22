"""Stable topological ordering of `@dataflow:` blocks (passes.md, `order_dataflow`)."""

import heapq
from collections.abc import Callable

from kohakunode.syntax.ast import Assign, Call, Dataflow, Program, Stmt, children, reads, writes


class DataflowCycle(Exception):
    def __init__(self, stmts: list[Stmt]):
        self.stmts = stmts
        super().__init__("dependency cycle in @dataflow block")


def order_block(stmts: list[Stmt], is_ordered: Callable[[Stmt], bool]) -> list[Stmt]:
    """Statements after every statement whose output they read; earliest first when tied."""
    deps: list[set[int]] = [set() for _ in stmts]
    writers: dict[str, list[int]] = {}
    for i, s in enumerate(stmts):
        for name in writes(s):
            writers.setdefault(name, []).append(i)
    last_ordered = None
    for i, s in enumerate(stmts):
        for name in reads(s):
            deps[i] |= {j for j in writers.get(name, []) if j != i}
        if is_ordered(s):
            if last_ordered is not None:
                deps[i].add(last_ordered)
            last_ordered = i
    remaining = [len(d) for d in deps]
    users: list[list[int]] = [[] for _ in stmts]
    for i, d in enumerate(deps):
        for j in d:
            users[j].append(i)
    ready = [i for i, r in enumerate(remaining) if r == 0]
    heapq.heapify(ready)
    out = []
    while ready:
        i = heapq.heappop(ready)
        out.append(stmts[i])
        for u in users[i]:
            remaining[u] -= 1
            if remaining[u] == 0:
                heapq.heappush(ready, u)
    if len(out) != len(stmts):
        raise DataflowCycle([stmts[i] for i, r in enumerate(remaining) if r > 0])
    return out


def _sort(stmts: list[Stmt], is_ordered) -> list[Stmt]:
    out = []
    for s in stmts:
        if isinstance(s, Dataflow):
            s = Dataflow(
                order_block(s.body, is_ordered),
                meta=s.meta,
                hint=s.hint,
                line=s.line,
                origin=s.origin,
            )
        for body in children(s):
            body[:] = _sort(body, is_ordered)
        out.append(s)
    return out


def sort_dataflow(program: Program, is_ordered: Callable[[Stmt], bool] = lambda s: False) -> None:
    """Sort every `@dataflow:` block in place; a `@mode dataflow` file is one block."""
    if program.mode == "dataflow":
        program.body = order_block(program.body, is_ordered)
    program.body = _sort(program.body, is_ordered)


def is_simple(s: Stmt) -> bool:
    return isinstance(s, (Assign, Call))
