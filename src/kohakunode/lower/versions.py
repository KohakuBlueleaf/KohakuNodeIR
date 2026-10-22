"""The ``version`` pass: every write gets its own version (passes.md).

A read reached by one write reads that write's version ``x__n``. A name read
somewhere with several writes reaching it gets a home version ``x__0``: each of
its writes is followed by ``x__0 = x__n`` and those reads read ``x__0``. The
home version is the flat name itself, so it is right on every path, including
the paths out of a failing `@try` body.
"""

from kohakunode.flow.cfg import UNDEF, build_cfg, defs_of, reaching
from kohakunode.origins import derive_origin
from kohakunode.syntax.ast import (
    Arg,
    Assign,
    Branch,
    Call,
    Collect,
    Name,
    Program,
    Stmt,
    Switch,
    Try,
    children,
    walk,
)


def _home(name: str) -> str:
    return f"{name}__0"


def version_program(program: Program) -> None:
    if any(isinstance(stmt, Collect) for stmt in walk(program.body)):
        raise ValueError("version needs expand_collect while collect remains")
    g = build_cfg(program.body)
    inn = reaching(g)
    # Version numbers in text order.
    counters: dict[str, int] = {}
    version: dict[tuple[int, str], str] = {}  # (cfg node, name) -> versioned name
    for s in walk(program.body):
        n = g.binds.get(id(s), g.node_of.get(id(s)))
        if n is None:
            continue
        for name in g.nodes[n].writes:
            counters[name] = counters.get(name, 0) + 1
            version[(n, name)] = f"{name}__{counters[name]}"
    # Which reads need a home version.
    reach = g.reachable()
    read_map: dict[tuple[int, str], str] = {}
    homes: set[str] = set()
    for n in reach:
        for name in g.nodes[n].reads:
            ds = defs_of(inn[n], name) - {UNDEF}
            if len(ds) == 1:
                read_map[(n, name)] = version[(next(iter(ds)), name)]
            else:
                homes.add(name)
                read_map[(n, name)] = _home(name)

    def read(n: int | None, e):
        if not isinstance(e, Name):
            return e
        return Name(read_map.get((n, e.id), _home(e.id)))

    def wv(n: int | None, name: str | None) -> str | None:
        return None if name is None else version[(n, name)]

    def rewrite(stmts: list[Stmt]) -> list[Stmt]:
        out: list[Stmt] = []
        for s in stmts:
            n = g.node_of.get(id(s))
            copies: list[Stmt] = []
            handler_copy: Stmt | None = None
            match s:
                case Assign():
                    s.value = read(n, s.value)
                    old = s.target
                    s.target = wv(n, old)
                    if old in homes:
                        copies.append(
                            Assign(
                                _home(old),
                                Name(s.target),
                                line=s.line,
                                origin=derive_origin(s.origin, generated="version.home"),
                            )
                        )
                case Call():
                    s.args = [Arg(read(n, a.value), a.key) for a in s.args]
                    olds = s.outs
                    s.outs = [wv(n, o) for o in olds]
                    for old, new in zip(olds, s.outs):
                        if old is not None and old in homes:
                            copies.append(
                                Assign(
                                    _home(old),
                                    Name(new),
                                    line=s.line,
                                    origin=derive_origin(s.origin, generated="version.home"),
                                )
                            )
                case Branch():
                    s.cond = read(n, s.cond)
                case Switch():
                    s.value = read(n, s.value)
                case Try():
                    if s.error_name:
                        old = s.error_name
                        s.error_name = version[(g.binds[id(s)], old)]
                        if old in homes:
                            handler_copy = Assign(
                                _home(old),
                                Name(s.error_name),
                                line=s.line,
                                origin=derive_origin(s.origin, generated="version.handler"),
                            )
            for body in children(s):
                body[:] = rewrite(body)
            # Added after the handler is rewritten: the copy is already versioned.
            if handler_copy is not None:
                s.handler.insert(0, handler_copy)
            out.append(s)
            out.extend(copies)
        return out

    program.body = rewrite(program.body)
