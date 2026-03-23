from __future__ import annotations

from typing import Optional

from kohakunode.analyzer.errors import (
    DuplicateLabelError,
    DuplicateSubgraphError,
    UndefinedLabelError,
    UnreachableNamespaceWarning,
)
from kohakunode.ast.nodes import (
    Branch,
    DataflowBlock,
    Jump,
    Namespace,
    Parallel,
    Program,
    Statement,
    SubgraphDef,
    Switch,
)
from kohakunode.errors import KirAnalysisError


class ScopeAnalyzer:
    """Validates namespace/scope rules in a KohakuNodeIR program.

    Checks performed:
    - Duplicate namespace labels within the same scope
    - Undefined label references in branch/switch/jump/parallel
    - Unreachable namespaces (never targeted in their scope)
    - Duplicate @def subgraph names (program-wide)
    """

    def __init__(self) -> None:
        pass

    def analyze(self, program: Program) -> list[KirAnalysisError]:
        """Analyze a program for scope errors and warnings.

        Returns a list of KirAnalysisError instances (never raises).
        """
        errors: list[KirAnalysisError] = []
        self._check_duplicate_subgraphs(program.body, errors)
        self._analyze_scope(program.body, errors)
        return errors

    # ------------------------------------------------------------------
    # Duplicate @def subgraph names (program-wide, top-level only)
    # ------------------------------------------------------------------

    def _check_duplicate_subgraphs(
        self,
        stmts: list[Statement],
        errors: list[KirAnalysisError],
    ) -> None:
        seen: dict[str, Optional[int]] = {}
        for stmt in stmts:
            if isinstance(stmt, SubgraphDef):
                if stmt.name in seen:
                    errors.append(
                        DuplicateSubgraphError(
                            name=stmt.name,
                            first_line=seen[stmt.name],
                            duplicate_line=stmt.line,
                        )
                    )
                else:
                    seen[stmt.name] = stmt.line

    # ------------------------------------------------------------------
    # Recursive scope analysis
    # ------------------------------------------------------------------

    def _analyze_scope(
        self,
        stmts: list[Statement],
        errors: list[KirAnalysisError],
        ancestor_namespaces: set[str] | None = None,
    ) -> None:
        """Analyze one scope level (program body, namespace body, or subgraph body).

        Collects namespace names and label references at this level, checks
        all scope-level rules, then recurses into child scopes.

        ``ancestor_namespaces`` is the set of namespace labels visible from
        parent scopes.  ``jump`` can target these; ``branch``/``switch``/
        ``parallel`` cannot (they must reference sibling namespaces).
        """
        if ancestor_namespaces is None:
            ancestor_namespaces = set()

        # --- collect namespace definitions at this scope level ----------
        namespace_defs: dict[str, Optional[int]] = {}
        for stmt in stmts:
            if isinstance(stmt, Namespace):
                if stmt.name in namespace_defs:
                    errors.append(
                        DuplicateLabelError(
                            label_name=stmt.name,
                            first_line=namespace_defs[stmt.name],
                            duplicate_line=stmt.line,
                        )
                    )
                else:
                    namespace_defs[stmt.name] = stmt.line

        # --- collect all label references at this scope level -----------
        referenced_labels: dict[str, str] = {}
        jump_labels: dict[str, str] = {}
        for stmt in stmts:
            refs = self._collect_label_refs(stmt)
            for label, context in refs:
                referenced_labels[label] = context
                # Track jump refs separately — they can target ancestor scopes
                if isinstance(stmt, Jump):
                    jump_labels[label] = context

        # --- check undefined label references ---------------------------
        # All visible labels: current scope + ancestors (for jump only)
        for label, context in referenced_labels.items():
            if label in namespace_defs:
                continue
            # Jump can target ancestor-scope namespaces
            if label in jump_labels and label in ancestor_namespaces:
                continue
            errors.append(
                UndefinedLabelError(
                    label_name=label,
                    referenced_from=context,
                )
            )

        # --- check unreachable namespaces --------------------------------
        for ns_name, ns_line in namespace_defs.items():
            if ns_name not in referenced_labels:
                errors.append(
                    UnreachableNamespaceWarning(
                        label_name=ns_name,
                        line=ns_line,
                    )
                )

        # --- recurse into child scopes ----------------------------------
        child_ancestors = ancestor_namespaces | set(namespace_defs.keys())
        for stmt in stmts:
            if isinstance(stmt, Namespace):
                self._analyze_scope(stmt.body, errors, child_ancestors)
            elif isinstance(stmt, SubgraphDef):
                self._analyze_scope(stmt.body, errors)
            elif isinstance(stmt, DataflowBlock):
                self._analyze_scope(stmt.body, errors, child_ancestors)

    # ------------------------------------------------------------------
    # Label reference collection
    # ------------------------------------------------------------------

    def _collect_label_refs(self, stmt: Statement) -> list[tuple[str, str]]:
        """Return all (label_name, context_description) pairs referenced by stmt."""
        refs: list[tuple[str, str]] = []

        if isinstance(stmt, Branch):
            context = f"branch (line {stmt.line})" if stmt.line is not None else "branch"
            if stmt.true_label:
                refs.append((stmt.true_label, context))
            if stmt.false_label:
                refs.append((stmt.false_label, context))

        elif isinstance(stmt, Switch):
            context = f"switch (line {stmt.line})" if stmt.line is not None else "switch"
            for _expr, case_label in stmt.cases:
                if case_label:
                    refs.append((case_label, context))
            if stmt.default_label:
                refs.append((stmt.default_label, context))

        elif isinstance(stmt, Jump):
            context = f"jump (line {stmt.line})" if stmt.line is not None else "jump"
            if stmt.target:
                refs.append((stmt.target, context))

        elif isinstance(stmt, Parallel):
            context = (
                f"parallel (line {stmt.line})" if stmt.line is not None else "parallel"
            )
            for label in stmt.labels:
                if label:
                    refs.append((label, context))

        return refs
