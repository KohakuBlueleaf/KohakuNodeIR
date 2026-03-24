"""Tests for kohakunode.compiler.dataflow — DataflowCompiler."""


import pytest

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Identifier,
    Jump,
    Literal,
    Namespace,
    Parallel,
    Program,
    Switch,
)
from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.errors import KirCompilationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile(program: Program) -> Program:
    return DataflowCompiler().transform(program)


def _names_in_order(program: Program) -> list[str]:
    """Return func_name for FuncCall nodes and target for Assignment nodes."""
    result = []
    for stmt in program.body:
        if isinstance(stmt, FuncCall):
            result.append(stmt.func_name)
        elif isinstance(stmt, Assignment):
            result.append(f"={stmt.target}")
    return result


# ---------------------------------------------------------------------------
# test_non_dataflow_passthrough
# ---------------------------------------------------------------------------


def test_non_dataflow_program_returned_unchanged():
    """A program without mode='dataflow' is returned as-is (same object)."""
    prog = Program(
        body=[FuncCall(func_name="fn", inputs=[], outputs=["x"], line=1)],
        mode=None,
    )
    result = _compile(prog)
    assert result is prog


def test_non_dataflow_mode_control_flow_no_error():
    """Control-flow nodes in non-dataflow mode must not raise."""
    ns = Namespace(name="label", body=[], line=1)
    branch = Branch(condition=Identifier(name="c"), true_label="label", false_label="label", line=2)
    prog = Program(body=[ns, branch], mode=None)
    result = _compile(prog)
    assert result is prog


def test_non_dataflow_body_untouched():
    assign = Assignment(target="x", value=Literal(value=1, literal_type="int"), line=1)
    call = FuncCall(func_name="process", inputs=[Identifier(name="x")], outputs=["y"], line=2)
    prog = Program(body=[assign, call], mode=None)
    result = _compile(prog)
    assert result.body[0] is assign
    assert result.body[1] is call


# ---------------------------------------------------------------------------
# test_dataflow_compilation
# ---------------------------------------------------------------------------


def test_dataflow_compilation_clears_mode():
    """After compilation, program.mode is None."""
    call = FuncCall(func_name="fn", inputs=[], outputs=["x"], line=1)
    prog = Program(body=[call], mode="dataflow")
    result = _compile(prog)
    assert result.mode is None


def test_dataflow_compilation_topological_order_simple():
    """
    c depends on b, b depends on a.
    Input order: c, b, a.
    Expected sorted order: a, b, c.
    """
    # a = fn_a()
    call_a = FuncCall(func_name="fn_a", inputs=[], outputs=["a"], line=3)
    # b = fn_b(a)
    call_b = FuncCall(func_name="fn_b", inputs=[Identifier(name="a")], outputs=["b"], line=2)
    # c = fn_c(b)
    call_c = FuncCall(func_name="fn_c", inputs=[Identifier(name="b")], outputs=["c"], line=1)
    prog = Program(body=[call_c, call_b, call_a], mode="dataflow")
    result = _compile(prog)
    names = _names_in_order(result)
    # a must come before b; b must come before c
    assert names.index("fn_a") < names.index("fn_b")
    assert names.index("fn_b") < names.index("fn_c")


def test_dataflow_compilation_independent_nodes_all_present():
    """
    Two independent nodes (no shared dependencies) should both appear.
    """
    call_x = FuncCall(func_name="gen_x", inputs=[], outputs=["x"], line=1)
    call_y = FuncCall(func_name="gen_y", inputs=[], outputs=["y"], line=2)
    prog = Program(body=[call_x, call_y], mode="dataflow")
    result = _compile(prog)
    names = _names_in_order(result)
    assert "gen_x" in names
    assert "gen_y" in names
    assert len(result.body) == 2


def test_dataflow_compilation_assignment_ordered():
    """Assignment node: x must come before use of x."""
    assign = Assignment(target="raw", value=Literal(value=10, literal_type="int"), line=2)
    call = FuncCall(func_name="transform", inputs=[Identifier(name="raw")], outputs=["out"], line=1)
    prog = Program(body=[call, assign], mode="dataflow")
    result = _compile(prog)
    names = _names_in_order(result)
    assert names.index("=raw") < names.index("transform")


def test_dataflow_compilation_returns_new_program():
    """Dataflow compiler must return a new Program, not the original."""
    call = FuncCall(func_name="fn", inputs=[], outputs=["x"], line=1)
    prog = Program(body=[call], mode="dataflow")
    result = _compile(prog)
    assert result is not prog


# ---------------------------------------------------------------------------
# test_control_flow_rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "control_flow_stmt",
    [
        Namespace(name="ns", body=[], line=1),
        Branch(condition=Identifier(name="c"), true_label="a", false_label="b", line=1),
        Jump(target="somewhere", line=1),
        Parallel(labels=["a", "b"], line=1),
        Switch(value=Identifier(name="v"), cases=[], line=1),
    ],
    ids=["Namespace", "Branch", "Jump", "Parallel", "Switch"],
)
def test_dataflow_rejects_control_flow_node(control_flow_stmt):
    """Each control-flow construct raises KirCompilationError in dataflow mode."""
    prog = Program(body=[control_flow_stmt], mode="dataflow")
    with pytest.raises(KirCompilationError):
        _compile(prog)


def test_dataflow_compilation_error_message_contains_type():
    ns = Namespace(name="n", body=[], line=1)
    prog = Program(body=[ns], mode="dataflow")
    with pytest.raises(KirCompilationError) as exc_info:
        _compile(prog)
    assert "Namespace" in str(exc_info.value)


def test_dataflow_compiler_name():
    assert DataflowCompiler().name == "dataflow_to_sequential"
