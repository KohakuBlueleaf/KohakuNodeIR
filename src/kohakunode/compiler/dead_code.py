"""Dead code elimination pass — remove assignments whose outputs are never used."""

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    Expression,
    FuncCall,
    Identifier,
    KeywordArg,
    Namespace,
    Parallel,
    Program,
    Statement,
    SubgraphDef,
    Switch,
    TryExcept,
    TypeHintBlock,
    Wildcard,
)
from kohakunode.compiler.passes import IRPass


# ---------------------------------------------------------------------------
# DeadCodePass
# ---------------------------------------------------------------------------


class DeadCodePass(IRPass):
    """Remove assignments whose outputs are never referenced downstream.

    An assignment ``x = …`` is dead when ``x`` never appears as an input to
    any other statement in the same scope (or any nested scope).  A
    :class:`~kohakunode.ast.nodes.FuncCall` is *never* considered dead because
    it may have side effects even when all its outputs are unused.

    The pass operates per-scope: it analyses the entire flat statement list of
    each :class:`~kohakunode.ast.nodes.Namespace` / top-level body
    independently, then recurses into nested scopes.

    Scoped rules
    ------------
    - ``Assignment`` to a variable that is never used → removed.
    - ``FuncCall`` → always kept (side-effect-safe approach).
    - ``Branch``, ``Switch``, ``Jump``, ``Parallel`` → always kept.
    - ``TypeHintBlock`` → always kept (metadata, not executable).
    - ``Namespace``, ``SubgraphDef``, ``TryExcept`` → recurse into sub-bodies.
    """

    @property
    def name(self) -> str:
        return "dead_code"

    def transform(self, program: Program) -> Program:
        new_body = _eliminate_body(program.body)
        return Program(body=new_body, mode=program.mode, typehints=program.typehints)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_used_names(stmts: list[Statement]) -> set[str]:
    """Return all variable names *used* as inputs across *stmts*."""
    used: set[str] = set()
    for stmt in stmts:
        _collect_used_in_stmt(stmt, used)
    return used


def _collect_used_in_expr(expr: Expression, used: set[str]) -> None:
    match expr:
        case Identifier():
            used.add(expr.name)
        case KeywordArg():
            _collect_used_in_expr(expr.value, used)


def _collect_used_in_stmt(stmt: Statement, used: set[str]) -> None:
    match stmt:
        case Assignment():
            _collect_used_in_expr(stmt.value, used)

        case FuncCall():
            for inp in stmt.inputs:
                _collect_used_in_expr(inp, used)

        case Branch():
            _collect_used_in_expr(stmt.condition, used)

        case Switch():
            _collect_used_in_expr(stmt.value, used)
            for case_expr, _ in stmt.cases:
                _collect_used_in_expr(case_expr, used)

        case Namespace():
            for s in stmt.body:
                _collect_used_in_stmt(s, used)

        case SubgraphDef():
            for s in stmt.body:
                _collect_used_in_stmt(s, used)

        case TryExcept():
            for s in stmt.try_body:
                _collect_used_in_stmt(s, used)
            for s in stmt.except_body:
                _collect_used_in_stmt(s, used)


def _eliminate_body(stmts: list[Statement]) -> list[Statement]:
    """Eliminate dead assignments from *stmts* (one pass, fixed-point aware)."""
    # Fixed-point loop: keep eliminating until no more dead assignments exist.
    current = stmts
    while True:
        used = _collect_used_names(current)
        new_stmts: list[Statement] = []
        changed = False
        for stmt in current:
            match stmt:
                case Assignment():
                    if stmt.target not in used:
                        # Dead assignment — drop it
                        changed = True
                        continue
                    new_stmts.append(stmt)
                case Namespace():
                    new_body = _eliminate_body(stmt.body)
                    if new_body is not stmt.body and new_body != stmt.body:
                        changed = True
                    new_stmts.append(
                        Namespace(name=stmt.name, body=new_body, line=stmt.line)
                    )
                case SubgraphDef():
                    new_body = _eliminate_body(stmt.body)
                    if new_body != stmt.body:
                        changed = True
                    new_stmts.append(
                        SubgraphDef(
                            name=stmt.name,
                            params=stmt.params,
                            outputs=stmt.outputs,
                            body=new_body,
                            line=stmt.line,
                        )
                    )
                case TryExcept():
                    new_try = _eliminate_body(stmt.try_body)
                    new_except = _eliminate_body(stmt.except_body)
                    if new_try != stmt.try_body or new_except != stmt.except_body:
                        changed = True
                    new_stmts.append(
                        TryExcept(
                            try_body=new_try,
                            except_body=new_except,
                            metadata=stmt.metadata,
                            line=stmt.line,
                        )
                    )
                case _:
                    new_stmts.append(stmt)

        if not changed:
            return new_stmts
        current = new_stmts
