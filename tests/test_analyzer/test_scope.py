"""Tests for kohakunode.analyzer.scope — ScopeAnalyzer."""

from __future__ import annotations

import pytest

from kohakunode.analyzer.errors import (
    DuplicateLabelError,
    DuplicateSubgraphError,
    UndefinedLabelError,
    UnreachableNamespaceWarning,
)
from kohakunode.analyzer.scope import ScopeAnalyzer
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
    SubgraphDef,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _analyze(program: Program) -> list:
    return ScopeAnalyzer().analyze(program)


def _errors_of_type(errors, cls):
    return [e for e in errors if isinstance(e, cls)]


# ---------------------------------------------------------------------------
# test_valid_program
# ---------------------------------------------------------------------------


def test_valid_program_no_errors():
    """A correctly-formed program with namespaces and branches produces no errors."""
    ns_true = Namespace(name="on_true", body=[FuncCall(func_name="do_a")], line=3)
    ns_false = Namespace(name="on_false", body=[FuncCall(func_name="do_b")], line=5)
    branch = Branch(
        condition=Identifier(name="cond"),
        true_label="on_true",
        false_label="on_false",
        line=2,
    )
    assign = Assignment(
        target="cond",
        value=Literal(value=True, literal_type="bool"),
        line=1,
    )
    prog = Program(body=[assign, branch, ns_true, ns_false])
    errors = _analyze(prog)
    assert errors == []


def test_valid_program_with_jump():
    """Jump to an existing namespace produces no errors."""
    ns = Namespace(name="target", body=[FuncCall(func_name="fn")], line=2)
    jump = Jump(target="target", line=1)
    prog = Program(body=[jump, ns])
    errors = _analyze(prog)
    assert errors == []


def test_valid_program_no_namespaces():
    """Program with no namespaces and no jump/branch produces no errors."""
    prog = Program(
        body=[
            Assignment(target="x", value=Literal(value=1, literal_type="int"), line=1),
            FuncCall(func_name="process", inputs=[Identifier(name="x")], outputs=["y"], line=2),
        ]
    )
    errors = _analyze(prog)
    assert errors == []


# ---------------------------------------------------------------------------
# test_duplicate_label
# ---------------------------------------------------------------------------


def test_duplicate_label_detected():
    """Two Namespace nodes with the same name in the same scope is an error."""
    ns1 = Namespace(name="my_label", body=[], line=1)
    ns2 = Namespace(name="my_label", body=[], line=5)
    prog = Program(body=[ns1, ns2])
    errors = _analyze(prog)
    dup = _errors_of_type(errors, DuplicateLabelError)
    assert len(dup) == 1
    assert dup[0].label_name == "my_label"


def test_duplicate_label_first_line_recorded():
    ns1 = Namespace(name="loop", body=[], line=3)
    ns2 = Namespace(name="loop", body=[], line=10)
    prog = Program(body=[ns1, ns2])
    errors = _analyze(prog)
    dup = _errors_of_type(errors, DuplicateLabelError)
    assert dup[0].first_line == 3
    assert dup[0].duplicate_line == 10


def test_no_duplicate_different_names():
    ns1 = Namespace(name="alpha", body=[], line=1)
    ns2 = Namespace(name="beta", body=[], line=2)
    prog = Program(body=[ns1, ns2])
    errors = _analyze(prog)
    assert _errors_of_type(errors, DuplicateLabelError) == []


# ---------------------------------------------------------------------------
# test_undefined_label
# ---------------------------------------------------------------------------


def test_undefined_label_in_branch():
    """Branch referencing a namespace that does not exist is an error."""
    branch = Branch(
        condition=Identifier(name="cond"),
        true_label="exists",
        false_label="missing",
        line=1,
    )
    ns = Namespace(name="exists", body=[], line=2)
    prog = Program(body=[branch, ns])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedLabelError)
    assert len(undef) == 1
    assert undef[0].label_name == "missing"


def test_undefined_label_in_jump():
    jump = Jump(target="nowhere", line=1)
    prog = Program(body=[jump])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedLabelError)
    assert any(e.label_name == "nowhere" for e in undef)


def test_undefined_label_in_parallel():
    parallel = Parallel(labels=["task_a", "nonexistent"], line=1)
    ns = Namespace(name="task_a", body=[], line=2)
    prog = Program(body=[parallel, ns])
    errors = _analyze(prog)
    undef = _errors_of_type(errors, UndefinedLabelError)
    assert any(e.label_name == "nonexistent" for e in undef)


def test_all_branch_labels_defined_no_error():
    branch = Branch(
        condition=Identifier(name="cond"),
        true_label="yes",
        false_label="no",
        line=1,
    )
    ns_yes = Namespace(name="yes", body=[], line=2)
    ns_no = Namespace(name="no", body=[], line=3)
    prog = Program(body=[branch, ns_yes, ns_no])
    errors = _analyze(prog)
    assert _errors_of_type(errors, UndefinedLabelError) == []


# ---------------------------------------------------------------------------
# test_unreachable_warning
# ---------------------------------------------------------------------------


def test_unreachable_warning_namespace_with_no_incoming():
    """A Namespace that no branch/jump/parallel targets is unreachable."""
    ns = Namespace(name="orphan", body=[], line=1)
    prog = Program(body=[ns])
    errors = _analyze(prog)
    warn = _errors_of_type(errors, UnreachableNamespaceWarning)
    assert len(warn) == 1
    assert warn[0].label_name == "orphan"


def test_unreachable_warning_line_preserved():
    ns = Namespace(name="orphan", body=[], line=42)
    prog = Program(body=[ns])
    errors = _analyze(prog)
    warn = _errors_of_type(errors, UnreachableNamespaceWarning)
    assert warn[0].line == 42


def test_no_unreachable_warning_when_targeted_by_branch():
    branch = Branch(
        condition=Identifier(name="c"),
        true_label="ns_t",
        false_label="ns_f",
        line=1,
    )
    ns_t = Namespace(name="ns_t", body=[], line=2)
    ns_f = Namespace(name="ns_f", body=[], line=3)
    prog = Program(body=[branch, ns_t, ns_f])
    errors = _analyze(prog)
    warn = _errors_of_type(errors, UnreachableNamespaceWarning)
    assert warn == []


def test_no_unreachable_warning_when_targeted_by_jump():
    jump = Jump(target="destination", line=1)
    ns = Namespace(name="destination", body=[], line=2)
    prog = Program(body=[jump, ns])
    errors = _analyze(prog)
    warn = _errors_of_type(errors, UnreachableNamespaceWarning)
    assert warn == []


# ---------------------------------------------------------------------------
# test_duplicate_subgraph
# ---------------------------------------------------------------------------


def test_duplicate_subgraph_detected():
    sg1 = SubgraphDef(name="my_func", params=[], outputs=[], body=[], line=1)
    sg2 = SubgraphDef(name="my_func", params=[], outputs=[], body=[], line=10)
    prog = Program(body=[sg1, sg2])
    errors = _analyze(prog)
    dup = _errors_of_type(errors, DuplicateSubgraphError)
    assert len(dup) == 1
    assert dup[0].name == "my_func"


def test_duplicate_subgraph_lines_recorded():
    sg1 = SubgraphDef(name="proc", params=[], outputs=[], body=[], line=5)
    sg2 = SubgraphDef(name="proc", params=[], outputs=[], body=[], line=20)
    prog = Program(body=[sg1, sg2])
    errors = _analyze(prog)
    dup = _errors_of_type(errors, DuplicateSubgraphError)
    assert dup[0].first_line == 5
    assert dup[0].duplicate_line == 20


def test_different_subgraph_names_no_error():
    sg1 = SubgraphDef(name="func_a", params=[], outputs=[], body=[], line=1)
    sg2 = SubgraphDef(name="func_b", params=[], outputs=[], body=[], line=5)
    prog = Program(body=[sg1, sg2])
    errors = _analyze(prog)
    assert _errors_of_type(errors, DuplicateSubgraphError) == []


def test_subgraph_duplicate_error_is_kir_analysis_error():
    from kohakunode.errors import KirAnalysisError

    sg1 = SubgraphDef(name="f", params=[], outputs=[], body=[], line=1)
    sg2 = SubgraphDef(name="f", params=[], outputs=[], body=[], line=2)
    prog = Program(body=[sg1, sg2])
    errors = _analyze(prog)
    assert all(isinstance(e, KirAnalysisError) for e in errors)
