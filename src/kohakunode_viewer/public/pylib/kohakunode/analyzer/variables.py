from kohakunode.analyzer.errors import UndefinedVariableError, WildcardInInputError
from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    Expression,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    LabelRef,
    Literal,
    Namespace,
    Parallel,
    Program,
    Statement,
    SubgraphDef,
    Switch,
    Wildcard,
)
from kohakunode.errors import KirAnalysisError


class VariableAnalyzer:
    """Analyzes variable usage in a KohakuNodeIR program.

    Checks:
    - Undefined variable usage (best-effort sequential check)
    - Wildcard '_' appearing in input position
    - SubgraphDef parameter shadowing within the same signature
    """

    def __init__(self) -> None:
        pass

    def analyze(self, program: Program) -> list[KirAnalysisError]:
        """Walk the program body and return all variable-related errors found.

        Does not raise; all errors are collected and returned as a list.
        """
        errors: list[KirAnalysisError] = []
        defined: set[str] = set()
        self._walk_body(program.body, defined, errors, top_level=True)
        return errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _walk_body(
        self,
        body: list[Statement],
        defined: set[str],
        errors: list[KirAnalysisError],
        top_level: bool,
    ) -> None:
        """Walk a list of statements, mutating *defined* in place."""
        for stmt in body:
            self._check_statement(stmt, defined, errors, top_level=top_level)

    def _check_statement(
        self,
        stmt: Statement,
        defined: set[str],
        errors: list[KirAnalysisError],
        top_level: bool,
    ) -> None:
        if isinstance(stmt, Assignment):
            self._check_assignment(stmt, defined, errors)

        elif isinstance(stmt, FuncCall):
            self._check_funccall(stmt, defined, errors)

        elif isinstance(stmt, Namespace):
            # Recurse with a copy: outer defs are visible, inner defs don't
            # escape to the top-level defined set.
            inner_defined = set(defined)
            self._walk_body(stmt.body, inner_defined, errors, top_level=False)

        elif isinstance(stmt, DataflowBlock):
            # Walk body; definitions inside are visible after the block.
            self._walk_body(stmt.body, defined, errors, top_level=False)

        elif isinstance(stmt, SubgraphDef):
            self._check_subgraphdef(stmt, defined, errors)

        elif isinstance(stmt, Branch):
            self._check_expression_input(stmt.condition, defined, errors, stmt.line)

        elif isinstance(stmt, Switch):
            self._check_expression_input(stmt.value, defined, errors, stmt.line)

        elif isinstance(stmt, (Jump, Parallel)):
            # No variable inputs to check.
            pass

    def _check_assignment(
        self,
        stmt: Assignment,
        defined: set[str],
        errors: list[KirAnalysisError],
    ) -> None:
        # Check RHS first, then record LHS as defined.
        self._check_expression_input(stmt.value, defined, errors, stmt.line)
        if stmt.target and stmt.target != "_":
            defined.add(stmt.target)

    def _check_funccall(
        self,
        stmt: FuncCall,
        defined: set[str],
        errors: list[KirAnalysisError],
    ) -> None:
        # Check all inputs before recording outputs.
        for inp in stmt.inputs:
            if isinstance(inp, Wildcard):
                errors.append(WildcardInInputError(line=stmt.line))
            else:
                self._check_expression_input(inp, defined, errors, stmt.line)

        # Record non-wildcard outputs as defined.
        for out in stmt.outputs:
            if isinstance(out, str) and out and out != "_":
                defined.add(out)

    def _check_subgraphdef(
        self,
        stmt: SubgraphDef,
        defined: set[str],
        errors: list[KirAnalysisError],
    ) -> None:
        # Validate that parameter names don't shadow each other within the
        # same signature.
        seen_params: set[str] = set()
        for param in stmt.params:
            if param.name in seen_params:
                errors.append(
                    UndefinedVariableError(
                        variable_name=param.name,
                        line=param.line,
                        node_context=f"@def {stmt.name}: duplicate parameter '{param.name}'",
                    )
                )
            else:
                seen_params.add(param.name)

        # Analyze body with outer defs + param names pre-seeded.
        inner_defined = set(defined) | seen_params
        self._walk_body(stmt.body, inner_defined, errors, top_level=False)

    def _check_expression_input(
        self,
        expr: Expression,
        defined: set[str],
        errors: list[KirAnalysisError],
        line: int | None,
    ) -> None:
        """Recursively inspect an expression used in input position."""
        if isinstance(expr, Wildcard):
            errors.append(WildcardInInputError(line=line))

        elif isinstance(expr, Identifier):
            if expr.name == "_":
                errors.append(WildcardInInputError(line=line))
            elif expr.name and expr.name not in defined:
                errors.append(
                    UndefinedVariableError(
                        variable_name=expr.name,
                        line=line,
                    )
                )

        elif isinstance(expr, KeywordArg):
            # Recurse into the value side of a keyword argument.
            self._check_expression_input(expr.value, defined, errors, line)

        elif isinstance(expr, (Literal, LabelRef)):
            # Literals and label references are always valid inputs.
            pass
