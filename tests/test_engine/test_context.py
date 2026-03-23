import pytest

from kohakunode.ast.nodes import Assignment, Identifier, Literal
from kohakunode.engine.context import ExecutionContext, ExecutionFrame, VariableStore
from kohakunode.errors import KirRuntimeError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assignment(target: str, value: int) -> Assignment:
    return Assignment(target=target, value=Literal(value=value, literal_type="int"))


def _make_statements(n: int = 3) -> list:
    return [_make_assignment(f"x{i}", i) for i in range(n)]


# ---------------------------------------------------------------------------
# test_variable_store_set_get
# ---------------------------------------------------------------------------


def test_variable_store_set_get():
    store = VariableStore()
    store.set("x", 42)
    assert store.get("x") == 42


def test_variable_store_set_get_various_types():
    store = VariableStore()
    store.set("s", "hello")
    store.set("f", 3.14)
    store.set("b", True)
    store.set("n", None)

    assert store.get("s") == "hello"
    assert store.get("f") == 3.14
    assert store.get("b") is True
    assert store.get("n") is None


# ---------------------------------------------------------------------------
# test_variable_store_undefined
# ---------------------------------------------------------------------------


def test_variable_store_undefined():
    store = VariableStore()

    with pytest.raises(KirRuntimeError, match="Undefined variable"):
        store.get("missing")


# ---------------------------------------------------------------------------
# test_variable_store_override
# ---------------------------------------------------------------------------


def test_variable_store_override():
    store = VariableStore()
    store.set("x", 1)
    store.set("x", 99)
    assert store.get("x") == 99


# ---------------------------------------------------------------------------
# test_variable_store_snapshot
# ---------------------------------------------------------------------------


def test_variable_store_snapshot():
    store = VariableStore()
    store.set("a", 1)
    store.set("b", 2)

    snap = store.snapshot()

    assert snap == {"a": 1, "b": 2}

    # Snapshot is a copy — mutating it does not affect the store.
    snap["a"] = 999
    assert store.get("a") == 1


def test_variable_store_snapshot_empty():
    store = VariableStore()
    assert store.snapshot() == {}


# ---------------------------------------------------------------------------
# test_execution_frame
# ---------------------------------------------------------------------------


def test_execution_frame_initial_position():
    stmts = _make_statements(3)
    frame = ExecutionFrame(statements=stmts)

    assert frame.position == 0
    assert frame.namespace_name is None


def test_execution_frame_advance():
    stmts = _make_statements(3)
    frame = ExecutionFrame(statements=stmts)

    assert frame.statements[frame.position] is stmts[0]
    frame.position += 1
    assert frame.statements[frame.position] is stmts[1]


def test_execution_frame_namespace_name():
    stmts = _make_statements(2)
    frame = ExecutionFrame(statements=stmts, namespace_name="my_ns")
    assert frame.namespace_name == "my_ns"


# ---------------------------------------------------------------------------
# test_context_push_pop
# ---------------------------------------------------------------------------


def test_context_push_single_frame():
    ctx = ExecutionContext()
    stmts = _make_statements(2)
    ctx.push_frame(stmts, namespace_name="root")

    assert ctx.has_frames is True
    assert ctx.current_frame.namespace_name == "root"
    assert ctx.current_frame.statements is stmts


def test_context_push_pop():
    ctx = ExecutionContext()
    stmts_a = _make_statements(2)
    stmts_b = _make_statements(1)

    ctx.push_frame(stmts_a, namespace_name="outer")
    ctx.push_frame(stmts_b, namespace_name="inner")

    assert ctx.current_frame.namespace_name == "inner"

    ctx.pop_frame()
    assert ctx.current_frame.namespace_name == "outer"

    ctx.pop_frame()
    assert ctx.has_frames is False


def test_context_advance_moves_position():
    ctx = ExecutionContext()
    stmts = _make_statements(3)
    ctx.push_frame(stmts)

    assert ctx.current_frame.position == 0
    ctx.advance()
    assert ctx.current_frame.position == 1
    ctx.advance()
    assert ctx.current_frame.position == 2


def test_context_current_statement_returns_none_when_exhausted():
    ctx = ExecutionContext()
    stmts = _make_statements(1)
    ctx.push_frame(stmts)

    assert ctx.current_statement is stmts[0]
    ctx.advance()
    assert ctx.current_statement is None


def test_context_is_frame_exhausted():
    ctx = ExecutionContext()
    stmts = _make_statements(1)
    ctx.push_frame(stmts)

    assert ctx.is_frame_exhausted is False
    ctx.advance()
    assert ctx.is_frame_exhausted is True


# ---------------------------------------------------------------------------
# test_context_empty_stack
# ---------------------------------------------------------------------------


def test_context_current_frame_empty_stack_raises():
    ctx = ExecutionContext()

    with pytest.raises(KirRuntimeError, match="No active execution frame"):
        _ = ctx.current_frame


def test_context_pop_frame_empty_stack_raises():
    ctx = ExecutionContext()

    with pytest.raises(KirRuntimeError, match="execution stack is empty"):
        ctx.pop_frame()


def test_context_advance_empty_stack_raises():
    ctx = ExecutionContext()

    with pytest.raises(KirRuntimeError):
        ctx.advance()


def test_context_current_statement_empty_stack_raises():
    ctx = ExecutionContext()

    with pytest.raises(KirRuntimeError):
        _ = ctx.current_statement


def test_context_has_frames_false_when_empty():
    ctx = ExecutionContext()
    assert ctx.has_frames is False
