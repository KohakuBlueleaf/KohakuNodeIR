"""Tests for kohakunode.analyzer.variables — VariableAnalyzer."""

from __future__ import annotations

import pytest

from kohakunode.analyzer.errors import UndefinedVariableError, WildcardInInputError
from kohakunode.analyzer.variables import VariableAnalyzer
from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Identifier,
    KeywordArg,
    Literal,
    Namespace,
    Program,
    SubgraphDef,
    Parameter,
    Wildcard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _analyze(program: Program) -> list:
    return VariableAnalyzer().analyze(program)


def _errors_of_type(errors, cls):
    return [e for e in errors if isinstance(e, cls)]


# ---------------------------------------------------------------------------
# test_valid_variables
# ---------------------------------------------------------------------------


def test_valid_variables_simple_chain():
    """x = 1 → (x)fn(y) → no errors."""
    assign = Assignment(target="x", value=Literal(value=1, literal_type="int"), line=1)
    call = FuncCall(inputs=[Identifier(name="x")], func_name="fn", outputs=["y"], line=2)
    prog = Program(body=[assign, call])
    errors = _analyze(prog)
    assert errors == []


def test_valid_variables_literal_input():
    """Literal input never causes an undefined variable error."""
    call = FuncCall(
        inputs=[Literal(value=42, literal_type="int")],
        func_name="fn",
        outputs=["result"],
        line=1,
    )
    prog = Program(body=[call])
    errors = _analyze(prog)
    assert errors == []


def test_valid_variables_multiple_outputs():
    call1 = FuncCall(inputs=[], func_name="gen", outputs=["a", "b"], line=1)
    call2 = FuncCall(
        inputs=[Identifier(name="a"), Identifier(name="b")],
        func_name="combine",
        outputs=["c"],
        line=2,
    )
    prog = Program(body=[call1, call2])
    errors = _analyze(prog)
    assert errors == []


def test_valid_variables_keyword_arg_defined():
    assign = Assignment(target="mode_val", value=Literal(value="fast", literal_type="str"), line=1)
    call = FuncCall(
        inputs=[KeywordArg(name="mode", value=Identifier(name="mode_val"))],
        func_name="process",
        outputs=["out"],
        line=2,
    )
    prog = Program(body=[assign, call])
    errors = _analyze(prog)
    assert errors == []


def test_valid_variables_branch_uses_defined():
    assign = Assignment(
        target="cond",
        value=Literal(value=True, literal_type="bool"),
        line=1,
    )
    branch = Branch(
        condition=Identifier(name="cond"),
        true_label="yes",
        false_label="no",
        line=2,
    )
    prog = Program(body=[assign, branch])
    errors = _analyze(prog)
    assert _errors_of_type(errors, UndefinedVariableError) == []


# ---------------------------------------------------------------------------
# test_undefined_variable
# ---------------------------------------------------------------------------


def test_undefined_variable_in_func_call_input():
    """Using 'z' before it is defined should produce an UndefinedVariableError."""
    call = FuncCall(inputs=[Identifier(name="z")], func_name="fn", outputs=["out"], line=1)
    prog = Program(body=[call])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert len(undef) == 1
    assert undef[0].variable_name == "z"


def test_undefined_variable_in_assignment_rhs():
    assign = Assignment(target="y", value=Identifier(name="undefined_x"), line=1)
    prog = Program(body=[assign])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert any(e.variable_name == "undefined_x" for e in undef)


def test_undefined_variable_used_before_definition():
    """Using a variable on line 1 that is only defined on line 2 is an error."""
    call = FuncCall(inputs=[Identifier(name="x")], func_name="fn", outputs=["y"], line=1)
    assign = Assignment(target="x", value=Literal(value=1, literal_type="int"), line=2)
    prog = Program(body=[call, assign])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert any(e.variable_name == "x" for e in undef)


def test_undefined_variable_line_reported():
    call = FuncCall(inputs=[Identifier(name="missing")], func_name="fn", outputs=[], line=7)
    prog = Program(body=[call])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert undef[0].line == 7


def test_undefined_variable_in_branch_condition():
    branch = Branch(
        condition=Identifier(name="undefined_cond"),
        true_label="t",
        false_label="f",
        line=3,
    )
    prog = Program(body=[branch])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert any(e.variable_name == "undefined_cond" for e in undef)


def test_undefined_variable_keyword_arg_value():
    call = FuncCall(
        inputs=[KeywordArg(name="alpha", value=Identifier(name="not_defined"))],
        func_name="fn",
        outputs=[],
        line=1,
    )
    prog = Program(body=[call])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert any(e.variable_name == "not_defined" for e in undef)


# ---------------------------------------------------------------------------
# test_wildcard_in_input
# ---------------------------------------------------------------------------


def test_wildcard_in_input_position():
    """Using Wildcard as an input (not output) should produce WildcardInInputError."""
    call = FuncCall(inputs=[Wildcard()], func_name="fn", outputs=["out"], line=4)
    prog = Program(body=[call])
    errors = _analyze(prog)
    wild = _errors_of_type(errors, WildcardInInputError)
    assert len(wild) == 1


def test_wildcard_in_input_underscore_identifier():
    """Identifier(name='_') used as input is also a wildcard-in-input error."""
    call = FuncCall(inputs=[Identifier(name="_")], func_name="fn", outputs=["out"], line=2)
    prog = Program(body=[call])
    errors = _analyze(prog)
    wild = _errors_of_type(errors, WildcardInInputError)
    assert len(wild) >= 1


def test_wildcard_as_output_is_valid():
    """Wildcard in output position is fine — no WildcardInInputError."""
    call = FuncCall(
        inputs=[Literal(value=1, literal_type="int")],
        func_name="gen",
        outputs=[Wildcard()],
        line=1,
    )
    prog = Program(body=[call])
    errors = _analyze(prog)
    assert _errors_of_type(errors, WildcardInInputError) == []


def test_wildcard_in_input_line_reported():
    call = FuncCall(inputs=[Wildcard()], func_name="fn", outputs=[], line=9)
    prog = Program(body=[call])
    errors = _analyze(prog)
    wild = _errors_of_type(errors, WildcardInInputError)
    assert wild[0].line == 9


# ---------------------------------------------------------------------------
# test_namespace_variable_scope
# ---------------------------------------------------------------------------


def test_namespace_inherits_outer_variables():
    """Variables defined before a namespace are visible inside it."""
    assign = Assignment(target="x", value=Literal(value=5, literal_type="int"), line=1)
    inner_call = FuncCall(
        inputs=[Identifier(name="x")],
        func_name="use_x",
        outputs=["y"],
        line=3,
    )
    ns = Namespace(name="my_ns", body=[inner_call], line=2)
    prog = Program(body=[assign, ns])
    errors = _analyze(prog)
    assert _errors_of_type(errors, UndefinedVariableError) == []


def test_namespace_inner_variable_does_not_escape():
    """A variable defined inside a namespace is not visible after it."""
    inner_call = FuncCall(inputs=[], func_name="gen", outputs=["inner_var"], line=2)
    ns = Namespace(name="my_ns", body=[inner_call], line=1)
    # Using inner_var outside the namespace should be undefined.
    outer_call = FuncCall(
        inputs=[Identifier(name="inner_var")],
        func_name="consume",
        outputs=[],
        line=3,
    )
    prog = Program(body=[ns, outer_call])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert any(e.variable_name == "inner_var" for e in undef)


def test_namespace_undefined_variable_inside():
    """Undefined variable used inside namespace body is detected."""
    inner_call = FuncCall(
        inputs=[Identifier(name="ghost")],
        func_name="fn",
        outputs=[],
        line=3,
    )
    ns = Namespace(name="ns", body=[inner_call], line=2)
    prog = Program(body=[ns])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert any(e.variable_name == "ghost" for e in undef)


def test_subgraph_params_are_defined_in_body():
    """Parameters of a @def are pre-seeded as defined within its body."""
    body_call = FuncCall(
        inputs=[Identifier(name="param_a")],
        func_name="use_param",
        outputs=["result"],
        line=2,
    )
    sg = SubgraphDef(
        name="my_sg",
        params=[Parameter(name="param_a")],
        outputs=["result"],
        body=[body_call],
        line=1,
    )
    prog = Program(body=[sg])
    errors = _analyze(prog)
    assert _errors_of_type(errors, UndefinedVariableError) == []


def test_subgraph_undefined_variable_in_body():
    """Undefined variable inside subgraph body is detected."""
    body_call = FuncCall(
        inputs=[Identifier(name="not_a_param")],
        func_name="fn",
        outputs=[],
        line=2,
    )
    sg = SubgraphDef(
        name="sg",
        params=[Parameter(name="x")],
        outputs=[],
        body=[body_call],
        line=1,
    )
    prog = Program(body=[sg])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedVariableError)
    assert any(e.variable_name == "not_a_param" for e in undef)
