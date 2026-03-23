from __future__ import annotations

from dataclasses import dataclass, field

from kohakunode.analyzer.errors import UnreachableNamespaceWarning
from kohakunode.analyzer.scope import ScopeAnalyzer
from kohakunode.analyzer.variables import VariableAnalyzer
from kohakunode.ast.nodes import Program
from kohakunode.errors import KirAnalysisError


@dataclass
class ValidationResult:
    errors: list[KirAnalysisError] = field(default_factory=list)
    warnings: list[KirAnalysisError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def all_issues(self) -> list[KirAnalysisError]:
        return self.errors + self.warnings


def validate(program: Program) -> ValidationResult:
    """Run all analyzers on *program* and return a ValidationResult.

    Never raises; all issues are collected and categorised into errors vs
    warnings.  UnreachableNamespaceWarning instances are treated as warnings;
    everything else is an error.
    """
    raw: list[KirAnalysisError] = []
    raw.extend(ScopeAnalyzer().analyze(program))
    raw.extend(VariableAnalyzer().analyze(program))

    errors: list[KirAnalysisError] = []
    warnings: list[KirAnalysisError] = []
    for issue in raw:
        if isinstance(issue, UnreachableNamespaceWarning):
            warnings.append(issue)
        else:
            errors.append(issue)

    return ValidationResult(errors=errors, warnings=warnings)


def validate_or_raise(program: Program) -> ValidationResult:
    """Validate *program* and raise the first error if any errors are found.

    Warnings do not cause a raise.  The returned ValidationResult may still
    contain warnings even when no error is raised.
    """
    result = validate(program)
    if not result.is_valid:
        raise result.errors[0]
    return result
