import pathlib

import pytest

from kohakunode.engine.context import VariableStore
from kohakunode.engine.executor import Executor, run
from kohakunode.engine.registry import Registry
from kohakunode.errors import KirAnalysisError, KirRuntimeError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"


def _basic_registry() -> Registry:
    registry = Registry()
    registry.register("add", lambda a, b: a + b, output_names=["result"])
    registry.register("less_than", lambda a, b: a < b, output_names=["result"])
    registry.register("print", lambda v: None, output_names=[])
    return registry


# ---------------------------------------------------------------------------
# test_execute_source
# ---------------------------------------------------------------------------


def test_execute_source_simple_assignment():
    executor = Executor(validate=False)
    store = executor.execute_source("x = 42")

    assert isinstance(store, VariableStore)
    assert store.get("x") == 42


def test_execute_source_returns_variable_store():
    executor = Executor(validate=False)
    store = executor.execute_source("a = 1\nb = 2")

    snap = store.snapshot()
    assert snap["a"] == 1
    assert snap["b"] == 2


def test_execute_source_with_func_call():
    executor = Executor(registry=_basic_registry(), validate=False)
    store = executor.execute_source("(3, 7)add(total)")
    assert store.get("total") == 10


def test_execute_source_full_pipeline():
    """Smoke-test: parse -> validate -> compile -> interpret."""
    executor = Executor(registry=_basic_registry(), validate=True)
    source = (
        "x = 5\n"
        "y = 10\n"
        "(x, y)add(z)"
    )
    store = executor.execute_source(source)
    assert store.get("z") == 15


# ---------------------------------------------------------------------------
# test_execute_file
# ---------------------------------------------------------------------------


def test_execute_file_basic_assignment():
    """Run the basic_assignment.kir fixture through the executor."""
    executor = Executor(validate=False)
    store = executor.execute_file(FIXTURES_DIR / "basic_assignment.kir")

    assert isinstance(store, VariableStore)
    assert store.get("x") == 42
    assert store.get("name") == "hello"
    assert store.get("pi") == pytest.approx(3.14)
    assert store.get("flag") is True
    assert store.get("empty") is None


def test_execute_file_loop():
    """Run the loop.kir fixture; requires add and less_than."""
    executor = Executor(registry=_basic_registry(), validate=False)
    store = executor.execute_file(FIXTURES_DIR / "loop.kir")
    assert store.get("counter") == 5


def test_execute_file_path_as_string():
    """execute_file also accepts a plain string path."""
    executor = Executor(validate=False)
    store = executor.execute_file(str(FIXTURES_DIR / "basic_assignment.kir"))
    assert store.get("x") == 42


# ---------------------------------------------------------------------------
# test_register_chaining
# ---------------------------------------------------------------------------


def test_register_chaining_returns_self():
    executor = Executor()
    returned = executor.register("add", lambda a, b: a + b, output_names=["r"])
    assert returned is executor


def test_register_chaining_multiple():
    executor = (
        Executor()
        .register("add", lambda a, b: a + b, output_names=["result"])
        .register("negate", lambda x: -x, output_names=["result"])
    )
    assert executor.registry.has("add")
    assert executor.registry.has("negate")


def test_register_chaining_then_execute():
    store = (
        Executor(validate=False)
        .register("add", lambda a, b: a + b, output_names=["result"])
        .execute_source("(2, 3)add(ans)")
    )
    assert store.get("ans") == 5


# ---------------------------------------------------------------------------
# test_run_convenience
# ---------------------------------------------------------------------------


def test_run_convenience_simple():
    store = run("val = 99", validate=False)
    assert isinstance(store, VariableStore)
    assert store.get("val") == 99


def test_run_convenience_with_registry():
    registry = _basic_registry()
    store = run("(4, 6)add(total)", registry=registry, validate=False)
    assert store.get("total") == 10


def test_run_convenience_fresh_registry_when_none():
    """run() should work without an explicit registry for registry-free programs."""
    store = run("a = 1\nb = 2", validate=False)
    assert store.get("a") == 1
    assert store.get("b") == 2


def test_run_convenience_validate_true():
    """run() with validate=True should still succeed for valid programs."""
    store = run("x = 7", validate=True)
    assert store.get("x") == 7


# ---------------------------------------------------------------------------
# test_validation_on
# ---------------------------------------------------------------------------


def test_validation_on_catches_undefined_variable():
    """Validation should reject a program that reads an undefined variable."""
    executor = Executor(validate=True)
    # undefined_var.kir reads a variable that is never assigned.
    with pytest.raises((KirAnalysisError, KirRuntimeError)):
        executor.execute_file(FIXTURES_DIR / "errors" / "undefined_var.kir")


def test_validation_on_catches_bad_branch():
    """Validation should reject a branch targeting a non-existent namespace."""
    executor = Executor(validate=True)
    with pytest.raises((KirAnalysisError, KirRuntimeError)):
        executor.execute_file(FIXTURES_DIR / "errors" / "bad_branch.kir")


def test_validation_on_by_default():
    """Executor with no explicit validate= argument defaults to True."""
    executor = Executor()
    assert executor.validate is True


# ---------------------------------------------------------------------------
# test_validation_off
# ---------------------------------------------------------------------------


def test_validation_off_skips_analysis():
    """With validate=False a program that would fail analysis runs (or fails
    at runtime — either way, the analysis-level error is not raised)."""
    executor = Executor(validate=False)
    # We don't care whether it succeeds or raises a *runtime* error;
    # we only care it does NOT raise KirAnalysisError.
    try:
        executor.execute_file(FIXTURES_DIR / "errors" / "undefined_var.kir")
    except KirAnalysisError:
        pytest.fail("KirAnalysisError raised even with validate=False")
    except Exception:
        pass  # Runtime error is acceptable — we just skipped analysis.


def test_validation_off_flag_stored():
    executor = Executor(validate=False)
    assert executor.validate is False


def test_validation_off_valid_program_still_works():
    executor = Executor(validate=False)
    store = executor.execute_source("answer = 42")
    assert store.get("answer") == 42
