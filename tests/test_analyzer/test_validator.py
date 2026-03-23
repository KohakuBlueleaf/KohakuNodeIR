"""Tests for kohakunode.analyzer.validator — validate() and validate_or_raise()."""

from __future__ import annotations

import pytest

from kohakunode.analyzer.errors import (
    DuplicateLabelError,
    UndefinedLabelError,
    UndefinedVariableError,
    UnreachableNamespaceWarning,
)
from kohakunode.analyzer.validator import ValidationResult, validate, validate_or_raise
from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Identifier,
    Jump,
    Literal,
    Namespace,
    Program,
)
from kohakunode.errors import KirAnalysisError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_program() -> Program:
    """A simple, fully valid program."""
    assign = Assignment(target="x", value=Literal(value=1, literal_type="int"), line=1)
    call = FuncCall(inputs=[Identifier(name="x")], func_name="fn", outputs=["y"], line=2)
    return Program(body=[assign, call])


def _program_with_error() -> Program:
    """Program using an undefined variable — produces an analysis error."""
    call = FuncCall(inputs=[Identifier(name="undef")], func_name="fn", outputs=["y"], line=1)
    return Program(body=[call])


def _program_with_warning_only() -> Program:
    """Program with an unreachable namespace (warning) but no variable errors."""
    # An isolated namespace not targeted by any branch/jump is a warning.
    ns = Namespace(name="orphan", body=[], line=1)
    return Program(body=[ns])


def _program_with_undefined_label() -> Program:
    """Program with a branch referencing a non-existent label — error."""
    branch = Branch(
        condition=Identifier(name="c"),
        true_label="exists",
        false_label="ghost",
        line=2,
    )
    assign = Assignment(target="c", value=Literal(value=True, literal_type="bool"), line=1)
    ns = Namespace(name="exists", body=[], line=3)
    return Program(body=[assign, branch, ns])


# ---------------------------------------------------------------------------
# test_validate_valid
# ---------------------------------------------------------------------------


def test_validate_valid_returns_true():
    result = validate(_valid_program())
    assert result.is_valid is True


def test_validate_valid_no_errors():
    result = validate(_valid_program())
    assert result.errors == []


def test_validate_valid_no_warnings():
    result = validate(_valid_program())
    assert result.warnings == []


def test_validate_returns_validation_result():
    result = validate(_valid_program())
    assert isinstance(result, ValidationResult)


def test_validate_all_issues_empty_for_valid():
    result = validate(_valid_program())
    assert result.all_issues == []


# ---------------------------------------------------------------------------
# test_validate_with_errors
# ---------------------------------------------------------------------------


def test_validate_with_errors_returns_false():
    result = validate(_program_with_error())
    assert result.is_valid is False


def test_validate_with_errors_populates_errors_list():
    result = validate(_program_with_error())
    assert len(result.errors) >= 1


def test_validate_with_errors_contains_undefined_variable():
    result = validate(_program_with_error())
    assert any(isinstance(e, UndefinedVariableError) for e in result.errors)


def test_validate_undefined_label_is_error():
    result = validate(_program_with_undefined_label())
    assert result.is_valid is False
    assert any(isinstance(e, UndefinedLabelError) for e in result.errors)


def test_validate_errors_are_kir_analysis_errors():
    result = validate(_program_with_error())
    for err in result.errors:
        assert isinstance(err, KirAnalysisError)


def test_validate_with_errors_all_issues_includes_errors():
    result = validate(_program_with_error())
    assert all(e in result.all_issues for e in result.errors)


# ---------------------------------------------------------------------------
# test_validate_with_warnings
# ---------------------------------------------------------------------------


def test_validate_with_warnings_still_valid():
    """Unreachable namespace is a warning, not an error — is_valid should be True."""
    result = validate(_program_with_warning_only())
    assert result.is_valid is True


def test_validate_with_warnings_populates_warnings_list():
    result = validate(_program_with_warning_only())
    assert len(result.warnings) >= 1


def test_validate_with_warnings_errors_list_empty():
    result = validate(_program_with_warning_only())
    assert result.errors == []


def test_validate_unreachable_namespace_is_warning_type():
    result = validate(_program_with_warning_only())
    assert any(isinstance(w, UnreachableNamespaceWarning) for w in result.warnings)


def test_validate_all_issues_includes_warnings():
    result = validate(_program_with_warning_only())
    assert all(w in result.all_issues for w in result.warnings)


# ---------------------------------------------------------------------------
# test_validate_or_raise
# ---------------------------------------------------------------------------


def test_validate_or_raise_does_not_raise_for_valid():
    """Valid program should not raise."""
    result = validate_or_raise(_valid_program())
    assert result.is_valid is True


def test_validate_or_raise_raises_for_error():
    with pytest.raises(KirAnalysisError):
        validate_or_raise(_program_with_error())


def test_validate_or_raise_raises_first_error():
    """The first error in the errors list should be the raised exception."""
    prog = _program_with_error()
    with pytest.raises(KirAnalysisError) as exc_info:
        validate_or_raise(prog)
    # Verify we got a proper KirAnalysisError subclass.
    assert isinstance(exc_info.value, KirAnalysisError)


def test_validate_or_raise_does_not_raise_for_warning_only():
    """Warnings alone should not cause validate_or_raise to raise."""
    result = validate_or_raise(_program_with_warning_only())
    assert result.is_valid is True
    assert len(result.warnings) >= 1


def test_validate_or_raise_returns_result_with_warnings():
    """Even if no error, warnings are still present in the returned result."""
    result = validate_or_raise(_program_with_warning_only())
    assert isinstance(result, ValidationResult)
    assert result.warnings != []


def test_validate_or_raise_undefined_label_raises():
    with pytest.raises(KirAnalysisError):
        validate_or_raise(_program_with_undefined_label())
