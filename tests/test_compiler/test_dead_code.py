"""Dead code elimination tests for DeadCodePass.

Covers:
- Unused assignment removed
- Used assignment kept
- Side-effect calls (FuncCall) never removed
- Chain: if B depends on A and B is unused, both A and B removed
- Nested scopes (Namespace, SubgraphDef, TryExcept)
- TypeHintBlock always kept
"""

import pytest

from kohakunode import parse
from kohakunode.ast.nodes import Assignment, FuncCall, Namespace, Program, TypeHintBlock
from kohakunode.compiler.dead_code import DeadCodePass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _eliminate(source: str) -> Program:
    """Parse *source* and run DeadCodePass; return resulting Program."""
    prog = parse(source)
    return DeadCodePass().transform(prog)


def _stmt_summary(prog: Program) -> list[str]:
    """Return a list of human-readable statement descriptors for assertions."""
    result = []
    for stmt in prog.body:
        if isinstance(stmt, Assignment):
            result.append(f"assign:{stmt.target}")
        elif isinstance(stmt, FuncCall):
            result.append(f"call:{stmt.func_name}")
        elif isinstance(stmt, Namespace):
            result.append(f"ns:{stmt.name}")
        elif isinstance(stmt, TypeHintBlock):
            result.append("typehint")
        else:
            result.append(type(stmt).__name__)
    return result


def _names_in_body(prog: Program) -> set[str]:
    """Return all assignment target names in top-level body."""
    return {
        stmt.target for stmt in prog.body if isinstance(stmt, Assignment)
    }


# ---------------------------------------------------------------------------
# Basic elimination
# ---------------------------------------------------------------------------


def test_unused_assignment_removed() -> None:
    """A simple unused assignment is eliminated."""
    src = "unused = 42\n"
    result = _eliminate(src)
    assert "unused" not in _names_in_body(result)


def test_used_assignment_kept() -> None:
    """An assignment that is consumed by a FuncCall is kept."""
    src = "x = 10\n(x)identity(y)\n"
    result = _eliminate(src)
    assert "x" in _names_in_body(result)


def test_multiple_unused_assignments_all_removed() -> None:
    """All unused assignments are eliminated in one pass."""
    src = "a = 1\nb = 2\nc = 3\n"
    result = _eliminate(src)
    assert _names_in_body(result) == set()


def test_used_assignment_among_unused_kept() -> None:
    """Only the used assignment survives when there are unused ones too."""
    src = "a = 1\nb = 2\nused = 99\n(used)identity(out)\n"
    result = _eliminate(src)
    assert "used" in _names_in_body(result)
    assert "a" not in _names_in_body(result)
    assert "b" not in _names_in_body(result)


def test_assignment_used_by_another_assignment_kept() -> None:
    """x is used in y = x; both should be kept if y is also used."""
    src = "x = 5\ny = x\n(y)identity(out)\n"
    result = _eliminate(src)
    assert "x" in _names_in_body(result)
    assert "y" in _names_in_body(result)


# ---------------------------------------------------------------------------
# Side-effect calls are never removed
# ---------------------------------------------------------------------------


def test_side_effect_call_print_kept() -> None:
    """A FuncCall (print) with no outputs is always kept."""
    src = '("hello")print()\n'
    result = _eliminate(src)
    calls = [s for s in result.body if isinstance(s, FuncCall)]
    assert len(calls) == 1
    assert calls[0].func_name == "print"


def test_side_effect_call_with_wildcard_kept() -> None:
    """A FuncCall with all-wildcard outputs is always kept."""
    src = "(x)side_effect(_)\n"
    result = _eliminate(src)
    calls = [s for s in result.body if isinstance(s, FuncCall)]
    assert len(calls) == 1


def test_func_call_with_used_output_kept() -> None:
    """A FuncCall whose output is consumed by another statement is kept."""
    src = "(5, 3)add(sum)\n(sum)print()\n"
    result = _eliminate(src)
    calls = [s for s in result.body if isinstance(s, FuncCall)]
    func_names = {c.func_name for c in calls}
    assert "add" in func_names
    assert "print" in func_names


def test_func_call_with_unused_output_still_kept() -> None:
    """A FuncCall is kept even when ALL its outputs are unused (side effects)."""
    src = "(5, 3)add(unused_sum)\n"
    result = _eliminate(src)
    calls = [s for s in result.body if isinstance(s, FuncCall)]
    assert len(calls) == 1
    assert calls[0].func_name == "add"


# ---------------------------------------------------------------------------
# Chain elimination
# ---------------------------------------------------------------------------


def test_chain_b_depends_on_a_both_unused() -> None:
    """If B = f(A) and B is unused, and A is only used by B, both are removed."""
    src = "a = 10\nb = a\n"
    result = _eliminate(src)
    # b is unused, a is only used to compute b (which is unused)
    assert _names_in_body(result) == set()


def test_chain_three_levels_all_unused() -> None:
    """A three-level chain where the final output is unused: all removed."""
    src = "a = 1\nb = a\nc = b\n"
    result = _eliminate(src)
    assert _names_in_body(result) == set()


def test_chain_partial_use() -> None:
    """B uses A, C uses B; if only C is consumed, A and B are kept transitively."""
    src = "a = 1\nb = a\nc = b\n(c)print()\n"
    result = _eliminate(src)
    assert "a" in _names_in_body(result)
    assert "b" in _names_in_body(result)
    assert "c" in _names_in_body(result)


def test_chain_intermediate_unused_branch() -> None:
    """Two branches from A: one consumed, one not. Only the used branch survives."""
    src = "a = 5\nb = a\nc = a\n(b)print()\n"
    result = _eliminate(src)
    # a is kept (used by b), b is kept (used by print)
    assert "a" in _names_in_body(result)
    assert "b" in _names_in_body(result)
    # c is dead (only assigned, never used)
    assert "c" not in _names_in_body(result)


# ---------------------------------------------------------------------------
# Fixed-point convergence
# ---------------------------------------------------------------------------


def test_fixed_point_two_levels() -> None:
    """Dead code elimination converges when one removal creates new dead code."""
    # After 'b' is removed, 'a' becomes dead (only used by 'b')
    src = "a = 10\nb = a\nc = 99\n(c)print()\n"
    result = _eliminate(src)
    assert "c" in _names_in_body(result)
    # a and b are only in a dead chain
    assert "a" not in _names_in_body(result)
    assert "b" not in _names_in_body(result)


# ---------------------------------------------------------------------------
# Namespace scoping
# ---------------------------------------------------------------------------


def test_namespace_body_unused_assignments_removed() -> None:
    """Unused assignments inside a Namespace body are eliminated."""
    src = "x = 1\nmy_ns:\n    dead = 999\n    used = 42\n    (used)print()\n"
    result = _eliminate(src)
    # Find the namespace
    nss = [s for s in result.body if isinstance(s, Namespace)]
    assert len(nss) == 1
    ns = nss[0]
    ns_names = {s.target for s in ns.body if isinstance(s, Assignment)}
    assert "used" in ns_names
    assert "dead" not in ns_names


def test_top_level_unused_with_namespace_kept() -> None:
    """Top-level unused assignment removed; Namespace itself is always kept."""
    src = "dead = 1\nmy_ns:\n    x = 5\n    (x)print()\n"
    result = _eliminate(src)
    assert "dead" not in _names_in_body(result)
    nss = [s for s in result.body if isinstance(s, Namespace)]
    assert len(nss) == 1


# ---------------------------------------------------------------------------
# TryExcept scoping
# ---------------------------------------------------------------------------


def test_try_body_dead_assignment_removed() -> None:
    """Dead assignment inside @try body is eliminated."""
    from kohakunode.ast.nodes import TryExcept

    src = "@try:\n    dead = 1\n    (5)print()\n@except:\n    ok = True\n"
    result = _eliminate(src)
    try_excepts = [s for s in result.body if isinstance(s, TryExcept)]
    assert len(try_excepts) == 1
    te = try_excepts[0]
    try_names = {s.target for s in te.try_body if isinstance(s, Assignment)}
    assert "dead" not in try_names


def test_except_body_dead_assignment_removed() -> None:
    """Dead assignment inside @except body is eliminated."""
    from kohakunode.ast.nodes import TryExcept

    src = "@try:\n    (1)print()\n@except:\n    dead_in_except = 99\n"
    result = _eliminate(src)
    try_excepts = [s for s in result.body if isinstance(s, TryExcept)]
    te = try_excepts[0]
    except_names = {s.target for s in te.except_body if isinstance(s, Assignment)}
    assert "dead_in_except" not in except_names


# ---------------------------------------------------------------------------
# TypeHintBlock always kept
# ---------------------------------------------------------------------------


def test_typehint_block_always_kept() -> None:
    """@typehint: block is never eliminated by DeadCodePass."""
    src = "@typehint:\n    (int, int)add(int)\n\nunused = 1\n"
    prog = parse(src)
    result = DeadCodePass().transform(prog)
    # typehints on Program should be preserved
    assert result.typehints is not None
    assert len(result.typehints) == 1


# ---------------------------------------------------------------------------
# Pass is idempotent
# ---------------------------------------------------------------------------


def test_pass_idempotent() -> None:
    """Applying DeadCodePass twice gives the same result."""
    src = "a = 1\nb = 2\nused = 99\n(used)print()\n"
    prog = parse(src)
    once = DeadCodePass().transform(prog)
    twice = DeadCodePass().transform(once)
    assert _names_in_body(once) == _names_in_body(twice)


def test_pass_returns_program_when_nothing_to_eliminate() -> None:
    """When no dead code exists, the pass returns the same program."""
    src = "x = 10\n(x)print()\n"
    prog = parse(src)
    result = DeadCodePass().transform(prog)
    # At minimum all assignments present in input are still present in output
    assert _names_in_body(result) == {"x"}
