"""Tests for the pluggable execution backend (backend.py).

Covers: DefaultBackend backward compat, CachingBackend, lifecycle hooks,
metadata passthrough, custom backends, and convenience functions.
"""

import pathlib
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

import kohakunode
from kohakunode.engine.backend import (
    CachingBackend,
    DefaultBackend,
    ExecutionBackend,
    NodeInvocation,
)
from kohakunode.engine.executor import Executor, run, run_file
from kohakunode.engine.registry import Registry
from kohakunode.parser.parser import parse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"


def _make_registry() -> Registry:
    reg = Registry()
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("negate", lambda x: -x, output_names=["result"])
    return reg


# ---------------------------------------------------------------------------
# A. DefaultBackend backward compatibility
# ---------------------------------------------------------------------------


def test_no_backend_specified():
    """Executor without explicit backend auto-creates DefaultBackend."""
    reg = _make_registry()
    store = Executor(registry=reg, validate=False).execute_source("(3, 4)add(r)")
    assert store.get("r") == 7


def test_explicit_default_backend():
    """Passing DefaultBackend explicitly gives the same result."""
    reg = _make_registry()
    store = Executor(
        registry=reg, backend=DefaultBackend(), validate=False
    ).execute_source("(3, 4)add(r)")
    assert store.get("r") == 7


def test_default_with_control_flow():
    """Branch/loop works through the default backend."""
    reg = _make_registry()
    reg.register("less_than", lambda a, b: a < b, output_names=["result"])
    source = (
        "counter = 0\n"
        "limit = 3\n"
        "()jump(`loop_body`)\n"
        "loop_body:\n"
        "    (counter, 1)add(counter)\n"
        "    (counter, limit)less_than(keep_going)\n"
        "    (keep_going)branch(`continue_loop`, `exit_loop`)\n"
        "    continue_loop:\n"
        "        ()jump(`loop_body`)\n"
        "    exit_loop:"
    )
    store = Executor(
        registry=reg, backend=DefaultBackend(), validate=False
    ).execute_source(source)
    assert store.get("counter") == 3


# ---------------------------------------------------------------------------
# B. CachingBackend
# ---------------------------------------------------------------------------


def test_cache_hit():
    """Same function + same inputs => only executed once."""
    call_count = 0

    def counting_add(a, b):
        nonlocal call_count
        call_count += 1
        return a + b

    reg = Registry()
    reg.register("add", counting_add, output_names=["result"])

    backend = CachingBackend()
    source = "(3, 4)add(r1)\n(3, 4)add(r2)"
    store = Executor(registry=reg, backend=backend, validate=False).execute_source(
        source
    )

    assert store.get("r1") == 7
    assert store.get("r2") == 7
    assert call_count == 1


def test_cache_miss():
    """Different inputs => both calls execute."""
    call_count = 0

    def counting_add(a, b):
        nonlocal call_count
        call_count += 1
        return a + b

    reg = Registry()
    reg.register("add", counting_add, output_names=["result"])

    backend = CachingBackend()
    source = "(3, 4)add(r1)\n(5, 6)add(r2)"
    store = Executor(registry=reg, backend=backend, validate=False).execute_source(
        source
    )

    assert store.get("r1") == 7
    assert store.get("r2") == 11
    assert call_count == 2


def test_invalidate_all():
    """After invalidate(), same call re-executes."""
    call_count = 0

    def counting_add(a, b):
        nonlocal call_count
        call_count += 1
        return a + b

    reg = Registry()
    reg.register("add", counting_add, output_names=["result"])

    backend = CachingBackend()
    executor = Executor(registry=reg, backend=backend, validate=False)

    executor.execute_source("(1, 2)add(r)")
    assert call_count == 1

    backend.invalidate()

    executor.execute_source("(1, 2)add(r)")
    assert call_count == 2


def test_invalidate_by_name():
    """Selective invalidation only clears the named function."""
    add_count = 0
    neg_count = 0

    def counting_add(a, b):
        nonlocal add_count
        add_count += 1
        return a + b

    def counting_negate(x):
        nonlocal neg_count
        neg_count += 1
        return -x

    reg = Registry()
    reg.register("add", counting_add, output_names=["result"])
    reg.register("negate", counting_negate, output_names=["result"])

    backend = CachingBackend()
    executor = Executor(registry=reg, backend=backend, validate=False)

    executor.execute_source("(1, 2)add(r1)\n(5)negate(r2)")
    assert add_count == 1
    assert neg_count == 1

    # Only invalidate "add"
    backend.invalidate("add")

    executor.execute_source("(1, 2)add(r1)\n(5)negate(r2)")
    assert add_count == 2  # re-executed
    assert neg_count == 1  # still cached


def test_unhashable_input():
    """Dict/list inputs don't crash — falls back gracefully."""
    reg = Registry()
    reg.register("identity", lambda x: x, output_names=["result"])

    backend = CachingBackend()
    # We need to pass a dict as an argument. Use a variable assignment.
    # The KIR language doesn't have dict literals, so we use a helper.
    reg.register("make_dict", lambda: {"key": "value"}, output_names=["result"])
    source = "()make_dict(d)\n(d)identity(r)"
    store = Executor(registry=reg, backend=backend, validate=False).execute_source(
        source
    )
    assert store.get("r") == {"key": "value"}


# ---------------------------------------------------------------------------
# C. Lifecycle hooks
# ---------------------------------------------------------------------------


class RecordingBackend(ExecutionBackend):
    """Backend that records lifecycle events for testing."""

    def __init__(self):
        self.enter_calls: list[NodeInvocation] = []
        self.exit_calls: list[tuple[NodeInvocation, Any, Exception | None]] = []

    def invoke(self, invocation: NodeInvocation) -> Any:
        return invocation.spec.func(**invocation.call_kwargs)

    def on_node_enter(self, invocation: NodeInvocation) -> None:
        self.enter_calls.append(invocation)

    def on_node_exit(
        self, invocation: NodeInvocation, result: Any, error: Exception | None
    ) -> None:
        self.exit_calls.append((invocation, result, error))


def test_on_node_enter_called():
    """Custom backend receives on_node_enter for each function call."""
    reg = _make_registry()
    backend = RecordingBackend()

    Executor(registry=reg, backend=backend, validate=False).execute_source(
        "(1, 2)add(r)"
    )

    assert len(backend.enter_calls) == 1
    assert backend.enter_calls[0].spec.name == "add"


def test_on_node_exit_success():
    """on_node_exit receives result and error=None on success."""
    reg = _make_registry()
    backend = RecordingBackend()

    Executor(registry=reg, backend=backend, validate=False).execute_source(
        "(10, 20)add(r)"
    )

    assert len(backend.exit_calls) == 1
    invocation, result, error = backend.exit_calls[0]
    assert result == 30
    assert error is None


def test_on_node_exit_on_error():
    """on_node_exit receives the exception when a function raises."""

    def boom(x):
        raise ValueError("kaboom")

    reg = Registry()
    reg.register("boom", boom, output_names=["result"])
    backend = RecordingBackend()

    with pytest.raises(ValueError, match="kaboom"):
        Executor(registry=reg, backend=backend, validate=False).execute_source(
            "(1)boom(r)"
        )

    assert len(backend.exit_calls) == 1
    _, result, error = backend.exit_calls[0]
    assert result is None
    assert isinstance(error, ValueError)


def test_hooks_receive_node_id():
    """@meta node_id is available in invocation.node_id."""
    reg = _make_registry()
    backend = RecordingBackend()

    source = '@meta node_id="n1"\n(1, 2)add(r)'
    Executor(registry=reg, backend=backend, validate=False).execute_source(source)

    assert len(backend.enter_calls) == 1
    assert backend.enter_calls[0].node_id == "n1"


# ---------------------------------------------------------------------------
# D. Metadata passthrough
# ---------------------------------------------------------------------------


def test_metadata_present():
    """@meta data reaches the backend via invocation.metadata."""
    reg = _make_registry()
    backend = RecordingBackend()

    source = '@meta node_id="abc" color="red"\n(1, 2)add(r)'
    Executor(registry=reg, backend=backend, validate=False).execute_source(source)

    meta = backend.enter_calls[0].metadata
    assert meta["node_id"] == "abc"
    assert meta["color"] == "red"


def test_metadata_absent():
    """Without @meta, metadata is an empty dict."""
    reg = _make_registry()
    backend = RecordingBackend()

    Executor(registry=reg, backend=backend, validate=False).execute_source(
        "(1, 2)add(r)"
    )

    assert backend.enter_calls[0].metadata == {}


# ---------------------------------------------------------------------------
# E. Custom backend
# ---------------------------------------------------------------------------


class DoublingBackend(ExecutionBackend):
    """Doubles all numeric results."""

    def invoke(self, invocation: NodeInvocation) -> Any:
        result = invocation.spec.func(**invocation.call_kwargs)
        if isinstance(result, (int, float)):
            return result * 2
        return result


class LoggingBackend(ExecutionBackend):
    """Records all (name, kwargs) tuples."""

    def __init__(self):
        self.log: list[tuple[str, dict[str, Any]]] = []

    def invoke(self, invocation: NodeInvocation) -> Any:
        self.log.append((invocation.spec.name, dict(invocation.call_kwargs)))
        return invocation.spec.func(**invocation.call_kwargs)


def test_transform_backend():
    """Backend that doubles all numeric results."""
    reg = _make_registry()
    store = Executor(
        registry=reg, backend=DoublingBackend(), validate=False
    ).execute_source("(3, 4)add(r)")
    # add(3,4) = 7, doubled = 14
    assert store.get("r") == 14


def test_logging_backend():
    """Backend that records all (name, kwargs) tuples."""
    reg = _make_registry()
    backend = LoggingBackend()

    Executor(registry=reg, backend=backend, validate=False).execute_source(
        "(10, 20)add(r)\n(r)negate(neg)"
    )

    assert len(backend.log) == 2
    assert backend.log[0] == ("add", {"a": 10, "b": 20})
    assert backend.log[1] == ("negate", {"x": 30})


def test_custom_with_executor():
    """Full integration: custom backend through the Executor pipeline."""
    reg = _make_registry()
    reg.register("less_than", lambda a, b: a < b, output_names=["result"])
    backend = DoublingBackend()

    source = (
        "x = 5\n"
        "y = 10\n"
        "(x, y)add(z)\n"  # 15 * 2 = 30
        "(z)negate(neg)"  # -30 * 2 = -60
    )
    store = Executor(registry=reg, backend=backend, validate=False).execute_source(
        source
    )
    assert store.get("z") == 30
    assert store.get("neg") == -60


# ---------------------------------------------------------------------------
# F. Convenience functions
# ---------------------------------------------------------------------------


def test_run_with_backend():
    """kohakunode.run(source, backend=backend) works."""
    reg = _make_registry()
    backend = LoggingBackend()

    store = run("(2, 3)add(r)", registry=reg, backend=backend, validate=False)
    assert store.get("r") == 5
    assert len(backend.log) == 1


def test_run_file_with_backend():
    """kohakunode.run_file(path, backend=backend) works."""
    reg = _make_registry()
    backend = LoggingBackend()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".kir", delete=False) as f:
        f.write("(10, 20)add(total)")
        tmp_path = f.name

    store = run_file(tmp_path, registry=reg, backend=backend, validate=False)
    assert store.get("total") == 30
    assert len(backend.log) == 1

    pathlib.Path(tmp_path).unlink()
