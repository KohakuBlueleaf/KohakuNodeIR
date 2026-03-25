"""@try/@except execution tests.

Verifies the semantics of TryExcept:
- Successful try: except body NOT executed.
- Failed try: except body IS executed.
- Nested try/except.
- Variable defined in try accessible in except (if try fails after definition).
- Side-effect tracking via a list collector.
"""

import pytest

from kohakunode.engine.interpreter import Interpreter
from kohakunode.engine.registry import Registry
from kohakunode.errors import KirRuntimeError
from kohakunode.parser.parser import parse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(**extras) -> Registry:
    """Return a Registry with standard test functions plus any extras."""
    reg = Registry()
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("identity", lambda v: v, output_names=["result"])
    reg.register("negate", lambda v: -v, output_names=["result"])
    reg.register("to_string", lambda v: str(v), output_names=["result"])
    for name, (func, out) in extras.items():
        reg.register(name, func, output_names=out)
    return reg


def _run(source: str, registry: Registry | None = None) -> dict:
    """Parse, run, and return variable snapshot."""
    if registry is None:
        registry = Registry()
    interp = Interpreter(registry)
    interp.run(parse(source))
    return interp.context.variables.snapshot()


# ---------------------------------------------------------------------------
# Successful try — except body NOT executed
# ---------------------------------------------------------------------------


def test_try_success_no_except_execution() -> None:
    """When try body succeeds, except body is never executed."""
    reg = _make_registry()
    src = """\
@try:
    (1, 2)add(result)
@except:
    result = 999
"""
    state = _run(src, reg)
    assert state["result"] == 3, "try succeeded: result should be 3, not fallback"


def test_try_success_except_variable_not_set() -> None:
    """A variable assigned only in except is absent when try succeeds."""
    reg = _make_registry()
    src = """\
@try:
    (5, 5)add(ok)
@except:
    error_flag = True
"""
    state = _run(src, reg)
    assert state["ok"] == 10
    assert "error_flag" not in state


def test_try_success_multiple_statements() -> None:
    """Multiple statements in successful try all execute."""
    reg = _make_registry()
    src = """\
@try:
    (1, 2)add(a)
    (3, 4)add(b)
    (a, b)add(total)
@except:
    total = 0
"""
    state = _run(src, reg)
    assert state["a"] == 3
    assert state["b"] == 7
    assert state["total"] == 10


def test_try_success_assignment() -> None:
    """Plain assignment inside try executes when try body succeeds."""
    reg = _make_registry()
    src = """\
@try:
    x = 42
@except:
    x = 0
"""
    state = _run(src, reg)
    assert state["x"] == 42


# ---------------------------------------------------------------------------
# Failed try — except body IS executed
# ---------------------------------------------------------------------------


def test_try_failure_except_runs() -> None:
    """When try body raises, except body executes."""
    reg = _make_registry()

    def always_fail(v):
        raise RuntimeError("intentional failure")

    reg.register("fail", always_fail, output_names=["result"])

    src = """\
@try:
    (1)fail(result)
@except:
    result = 0
"""
    state = _run(src, reg)
    assert state["result"] == 0


def test_try_failure_except_uses_fallback() -> None:
    """Except provides a fallback value when try fails."""
    reg = _make_registry()

    def bad_div(a, b):
        return a / b

    reg.register("divide", bad_div, output_names=["result"])

    src = """\
@try:
    (10, 0)divide(result)
@except:
    result = -1
"""
    state = _run(src, reg)
    assert state["result"] == -1


def test_try_failure_except_has_multiple_statements() -> None:
    """Except body with multiple statements all execute on failure."""
    reg = _make_registry()

    def explode(v):
        raise ValueError("boom")

    reg.register("explode", explode, output_names=[])

    src = """\
@try:
    (1)explode()
@except:
    error_code = 42
    message = "failed"
"""
    state = _run(src, reg)
    assert state["error_code"] == 42
    assert state["message"] == "failed"


def test_try_failure_try_variable_not_set() -> None:
    """Variable that would have been set by try is absent after failure."""
    reg = _make_registry()

    def fail(v):
        raise RuntimeError("fail")

    reg.register("fail", fail, output_names=["result"])

    src = """\
@try:
    (1)fail(computed)
@except:
    fallback = True
"""
    state = _run(src, reg)
    assert "computed" not in state
    assert state["fallback"] is True


def test_try_failure_at_second_statement() -> None:
    """Failure on second statement of try: first result is set, except runs."""
    reg = _make_registry()

    def fail_always(v):
        raise RuntimeError("second fails")

    reg.register("fail_always", fail_always, output_names=[])

    src = """\
@try:
    (1, 2)add(partial)
    (partial)fail_always()
@except:
    recovered = True
"""
    state = _run(src, reg)
    # partial was set before the failure
    assert state["partial"] == 3
    assert state["recovered"] is True


# ---------------------------------------------------------------------------
# Variable defined in try accessible in except
# ---------------------------------------------------------------------------


def test_try_partial_variable_visible_in_except() -> None:
    """Variable set before the failing statement is visible to except."""
    reg = _make_registry()

    def fail(v):
        raise RuntimeError("fail")

    reg.register("fail", fail, output_names=[])

    src = """\
x = 10
@try:
    (x, 5)add(partial_sum)
    (partial_sum)fail()
@except:
    (partial_sum)identity(recovered)
"""
    state = _run(src, reg)
    assert state["partial_sum"] == 15
    assert state["recovered"] == 15


def test_outer_variable_accessible_in_except() -> None:
    """Variables defined before the try block are accessible inside except."""
    reg = _make_registry()

    def fail(v):
        raise RuntimeError("x")

    reg.register("fail", fail, output_names=[])

    src = """\
default_val = 99
@try:
    (1)fail()
@except:
    (default_val)identity(result)
"""
    state = _run(src, reg)
    assert state["result"] == 99


# ---------------------------------------------------------------------------
# Nested try/except
# ---------------------------------------------------------------------------


def test_nested_try_inner_success_outer_unaffected() -> None:
    """Inner try succeeds: outer continues normally."""
    reg = _make_registry()
    src = """\
@try:
    @try:
        (1, 2)add(inner)
    @except:
        inner = 0
    (inner, 10)add(outer_result)
@except:
    outer_result = -1
"""
    state = _run(src, reg)
    assert state["inner"] == 3
    assert state["outer_result"] == 13


def test_nested_try_inner_fails_outer_succeeds() -> None:
    """Inner try fails and recovers: outer continues normally."""
    reg = _make_registry()

    def fail(v):
        raise RuntimeError("inner fail")

    reg.register("fail", fail, output_names=[])

    src = """\
@try:
    @try:
        (1)fail()
        inner = 99
    @except:
        inner = 0
    (inner, 100)add(outer_result)
@except:
    outer_result = -1
"""
    state = _run(src, reg)
    assert state["inner"] == 0
    assert state["outer_result"] == 100


def test_nested_try_outer_fails() -> None:
    """Outer try fails (after inner succeeds): outer except runs."""
    reg = _make_registry()

    def fail(v):
        raise RuntimeError("outer fail")

    reg.register("fail", fail, output_names=[])

    src = """\
@try:
    @try:
        (5, 5)add(inner)
    @except:
        inner = 0
    (inner)fail()
@except:
    outer_fallback = True
"""
    state = _run(src, reg)
    assert state["inner"] == 10
    assert state["outer_fallback"] is True


def test_double_nested_try_innermost_fails() -> None:
    """Deeply nested try: innermost fails, each level recovers."""
    reg = _make_registry()

    def fail(v):
        raise RuntimeError("deep fail")

    reg.register("fail", fail, output_names=[])

    src = """\
@try:
    @try:
        @try:
            (1)fail()
            deep = 99
        @except:
            deep = 1
    @except:
        deep = 2
@except:
    deep = 3
"""
    state = _run(src, reg)
    assert state["deep"] == 1


# ---------------------------------------------------------------------------
# Try/except after other statements
# ---------------------------------------------------------------------------


def test_try_except_after_assignments() -> None:
    """try/except executes after preceding assignments, uses their values."""
    reg = _make_registry()

    def risky(a, b):
        if b == 0:
            raise ZeroDivisionError
        return a / b

    reg.register("risky", risky, output_names=["result"])

    src = """\
numerator = 10
denominator = 0
@try:
    (numerator, denominator)risky(result)
@except:
    result = numerator
"""
    state = _run(src, reg)
    assert state["result"] == 10


def test_try_except_before_subsequent_statements() -> None:
    """Statements after try/except run normally, can see try result."""
    reg = _make_registry()
    src = """\
@try:
    (5, 3)add(base)
@except:
    base = 0

(base, 2)add(final)
"""
    state = _run(src, reg)
    assert state["base"] == 8
    assert state["final"] == 10


# ---------------------------------------------------------------------------
# Empty try or except bodies
# ---------------------------------------------------------------------------


def test_empty_except_on_failure_is_silent() -> None:
    """Failing try with empty except silently swallows the error."""
    reg = _make_registry()

    def fail():
        raise RuntimeError("silent")

    reg.register("fail", fail, input_names=[], output_names=[])

    src = """\
x = 1
@try:
    ()fail()
@except:
    x = 2
"""
    state = _run(src, reg)
    assert state["x"] == 2


def test_side_effect_in_try_not_undone() -> None:
    """Side effects that occurred before the failing call are not rolled back."""
    collected: list = []
    reg = _make_registry()
    reg.register("collect", lambda v: collected.append(v), output_names=[])

    def fail(v):
        raise RuntimeError("fail after collect")

    reg.register("fail", fail, output_names=[])

    src = """\
(42)collect()
@try:
    (1)fail()
@except:
    recovered = True
"""
    _run(src, reg)
    assert 42 in collected
