"""Integration tests — full pipeline: parse → validate → compile → execute."""

from __future__ import annotations

import pytest

from kohakunode.engine.executor import Executor, run
from kohakunode.engine.registry import Registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(**funcs) -> Registry:
    """Create a Registry pre-populated with the given name → callable mapping."""
    reg = Registry()
    for name, func in funcs.items():
        reg.register(name, func)
    return reg


def _exec(source: str, registry: Registry | None = None) -> dict:
    """Parse, validate, compile, and execute *source*. Return variable snapshot."""
    if registry is None:
        registry = Registry()
    return Executor(registry=registry).execute_source(source).snapshot()


# ---------------------------------------------------------------------------
# test_factorial
# ---------------------------------------------------------------------------


def test_factorial_base_case():
    """factorial(1) = 1 via iterative approach using branch + jump."""
    source = """\
n = 1
acc = 1
(n, 1)lte(done_cond)
(done_cond)branch(`done`, `continue_loop`)
continue_loop:
    (acc, n)mul(acc)
    (n, 1)sub(n)
    (n, 1)lte(done_cond)
    (done_cond)branch(`done`, `continue_loop`)
done:
"""
    reg = _make_registry(
        lte=lambda a, b: a <= b,
        mul=lambda a, b: a * b,
        sub=lambda a, b: a - b,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["acc"] == 1


def test_factorial_five():
    """Compute 5! = 120 iteratively.

    The loop-back pattern requires jumping into the loop namespace first, then
    using a nested namespace for the back-edge jump (mimicking the loop.kir fixture).
    """
    source = """\
n = 5
acc = 1
()jump(`loop_body`)
loop_body:
    (acc, n)mul(acc)
    (n, 1)sub(n)
    (n, 0)gt(keep_going)
    (keep_going)branch(`continue_loop`, `done`)
    continue_loop:
        ()jump(`loop_body`)
    done:
"""
    reg = _make_registry(
        gt=lambda a, b: a > b,
        mul=lambda a, b: a * b,
        sub=lambda a, b: a - b,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["acc"] == 120


# ---------------------------------------------------------------------------
# test_branch_and_continue
# ---------------------------------------------------------------------------


def test_branch_and_continue_true_path():
    """Branch to on_true; code after branch executes after namespace completes."""
    source = """\
cond = True
(cond)branch(`on_true`, `on_false`)
on_true:
    (42)identity(branch_result)
on_false:
    (0)identity(branch_result)
(branch_result)double(final)
"""
    reg = _make_registry(
        identity=lambda x: x,
        double=lambda x: x * 2,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["branch_result"] == 42
    assert snap["final"] == 84


def test_branch_and_continue_false_path():
    """Branch to on_false path; final value reflects the false branch."""
    source = """\
cond = False
(cond)branch(`on_true`, `on_false`)
on_true:
    (100)identity(branch_result)
on_false:
    (7)identity(branch_result)
(branch_result)double(final)
"""
    reg = _make_registry(
        identity=lambda x: x,
        double=lambda x: x * 2,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["branch_result"] == 7
    assert snap["final"] == 14


# ---------------------------------------------------------------------------
# test_data_processing_pipeline
# ---------------------------------------------------------------------------


def test_data_processing_pipeline_sequential():
    """Multiple function calls in sequence, each using previous outputs."""
    source = """\
raw = 10
(raw)double(step1)
(step1)add_one(step2)
(step2)negate(final)
"""
    reg = _make_registry(
        double=lambda x: x * 2,
        add_one=lambda x: x + 1,
        negate=lambda x: -x,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["raw"] == 10
    assert snap["step1"] == 20
    assert snap["step2"] == 21
    assert snap["final"] == -21


def test_data_processing_pipeline_with_two_inputs():
    """Function call using two separately-defined variables."""
    source = """\
a = 3
b = 4
(a, b)add(sum_ab)
(a, b)mul(prod_ab)
(sum_ab, prod_ab)add(total)
"""
    reg = _make_registry(
        add=lambda a, b: a + b,
        mul=lambda a, b: a * b,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["sum_ab"] == 7
    assert snap["prod_ab"] == 12
    assert snap["total"] == 19


# ---------------------------------------------------------------------------
# test_subgraph_call
# ---------------------------------------------------------------------------


def test_subgraph_call_basic():
    """Define and call a subgraph; verify outputs."""
    source = """\
@def (x, y)add_and_double(result):
    (x, y)add(s)
    (s)double(result)

(3, 4)add_and_double(answer)
"""
    reg = _make_registry(
        add=lambda x, y: x + y,
        double=lambda x: x * 2,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["answer"] == 14  # (3+4)*2


def test_subgraph_call_with_default_param():
    """Subgraph with a default parameter value."""
    source = """\
@def (x, scale=2)scaled(result):
    (x, scale)mul(result)

(5)scaled(r1)
(5, scale=3)scaled(r2)
"""
    reg = _make_registry(mul=lambda x, scale: x * scale)
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["r1"] == 10
    assert snap["r2"] == 15


# ---------------------------------------------------------------------------
# test_parallel_execution
# ---------------------------------------------------------------------------


def test_parallel_branches_both_execute():
    """Both parallel branches run; results from both are visible after."""
    source = """\
(5)double(a)
(10)triple(b)
()parallel(`branch_a`, `branch_b`)
branch_a:
    (a)negate(result_a)
branch_b:
    (b)negate(result_b)
(result_a, result_b)add(combined)
"""
    reg = _make_registry(
        double=lambda x: x * 2,
        triple=lambda x: x * 3,
        negate=lambda x: -x,
        add=lambda x, y: x + y,
    )
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["result_a"] == -10
    assert snap["result_b"] == -30
    assert snap["combined"] == -40


def test_parallel_independent_branches():
    """Two independent parallel branches each set their own variable."""
    source = """\
()parallel(`p1`, `p2`)
p1:
    (1)identity(x)
p2:
    (2)identity(y)
"""
    reg = _make_registry(identity=lambda x: x)
    result = Executor(registry=reg, validate=False).execute_source(source)
    snap = result.snapshot()
    assert snap["x"] == 1
    assert snap["y"] == 2
