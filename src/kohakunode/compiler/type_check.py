"""Type checking pass — validate variable types against @typehint declarations."""

from kohakunode.ast.nodes import (
    Assignment,
    FuncCall,
    Identifier,
    KeywordArg,
    Literal,
    Namespace,
    Program,
    Statement,
    SubgraphDef,
    TryExcept,
    TypeExpr,
    TypeHintBlock,
    TypeHintEntry,
    Wildcard,
)
from kohakunode.compiler.passes import IRPass
from kohakunode.errors import KirCompilationError


# ---------------------------------------------------------------------------
# TypeCheckError
# ---------------------------------------------------------------------------


class TypeCheckError(KirCompilationError):
    """Raised when one or more type mismatches are found during type checking."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        message = "Type check failed with {} error(s):\n{}".format(
            len(errors), "\n".join(f"  - {e}" for e in errors)
        )
        super().__init__(message)


# ---------------------------------------------------------------------------
# Type compatibility helpers
# ---------------------------------------------------------------------------


def _types_compatible(actual: TypeExpr, expected: TypeExpr) -> bool:
    """Return True if *actual* satisfies *expected*.

    Rules:
    - ``Any`` in either position matches everything (checked only when not a union).
    - Union expected: any member of the union matches (checked before Any-name shortcut).
    - Optional expected (``A?``): actual must be ``A`` or ``none``.
    - Actual is a union: all members of actual must be compatible with expected.
    - Exact name match (when neither is a union/optional).
    """
    # Expected is a union — actual must be compatible with at least one member.
    # Check this BEFORE the Any shortcut so that union_of takes priority over name.
    if expected.union_of is not None:
        return any(_types_compatible(actual, member) for member in expected.union_of)

    # Any matches everything (only when expected has no union_of)
    if expected.name == "Any" or actual.name == "Any":
        return True

    # Expected is optional (A?) — matches A or none
    if expected.is_optional:
        inner = TypeExpr(name=expected.name, is_optional=False)
        return _types_compatible(actual, inner) or actual.name == "none"

    # Actual is a union — all members must satisfy expected
    if actual.union_of is not None:
        return all(_types_compatible(member, expected) for member in actual.union_of)

    # Actual is optional — compatible if expected accepts optional or none
    if actual.is_optional:
        inner_actual = TypeExpr(name=actual.name, is_optional=False)
        return _types_compatible(inner_actual, expected) or _types_compatible(
            TypeExpr(name="none"), expected
        )

    # Plain name match
    return actual.name == expected.name


# ---------------------------------------------------------------------------
# TypeCheckPass
# ---------------------------------------------------------------------------


class TypeCheckPass(IRPass):
    """Validate that variable types match @typehint declarations.

    The pass collects all type information from:
    1. ``program.typehints`` — top-level @typehint entries.
    2. ``TypeHintBlock`` statements embedded in the body.
    3. ``Assignment.type_annotation`` — explicit per-variable type annotations.

    It then walks all :class:`~kohakunode.ast.nodes.FuncCall` statements and
    checks that the number of inputs matches the typehint (when available) and
    that each input's inferred type is compatible with the declared input type.

    All errors are collected before raising so the caller sees the full
    picture in one shot.
    """

    @property
    def name(self) -> str:
        return "type_check"

    def transform(self, program: Program) -> Program:
        """Run type checking on *program* and return it unchanged on success.

        Raises
        ------
        TypeCheckError
            If any type mismatches are found (all errors collected first).
        """
        # Build type environment: func_name -> TypeHintEntry
        type_env: dict[str, TypeHintEntry] = {}
        _collect_typehints(program, type_env)

        # Build variable type map from typed assignments: var_name -> TypeExpr
        var_types: dict[str, TypeExpr] = {}
        errors: list[str] = []

        _check_body(program.body, type_env, var_types, errors)

        if errors:
            raise TypeCheckError(errors)

        return program


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_typehints(program: Program, type_env: dict[str, TypeHintEntry]) -> None:
    """Populate *type_env* from program-level typehints and TypeHintBlock nodes."""
    if program.typehints:
        for entry in program.typehints:
            type_env[entry.func_name] = entry

    for stmt in program.body:
        if isinstance(stmt, TypeHintBlock):
            for entry in stmt.entries:
                type_env[entry.func_name] = entry


def _infer_expr_type(expr, var_types: dict[str, TypeExpr]) -> TypeExpr | None:
    """Return the :class:`TypeExpr` for *expr*, or ``None`` if unknown."""
    match expr:
        case Identifier():
            return var_types.get(expr.name)
        case Literal():
            return TypeExpr(name=expr.literal_type if expr.literal_type else "Any")
        case KeywordArg():
            return _infer_expr_type(expr.value, var_types)
    return None


def _check_body(
    stmts: list[Statement],
    type_env: dict[str, TypeHintEntry],
    var_types: dict[str, TypeExpr],
    errors: list[str],
) -> None:
    """Recursively type-check a list of statements, updating *var_types*."""
    for stmt in stmts:
        _check_stmt(stmt, type_env, var_types, errors)


def _check_stmt(
    stmt: Statement,
    type_env: dict[str, TypeHintEntry],
    var_types: dict[str, TypeExpr],
    errors: list[str],
) -> None:
    match stmt:
        case Assignment():
            # Record variable type from annotation
            if stmt.type_annotation is not None:
                var_types[stmt.target] = stmt.type_annotation
            elif stmt.target not in var_types:
                # Infer from the RHS if it's a literal or typed variable
                inferred = _infer_expr_type(stmt.value, var_types)
                if inferred is not None:
                    var_types[stmt.target] = inferred

        case FuncCall():
            hint = type_env.get(stmt.func_name)
            if hint is not None:
                # Check input count
                # Positional inputs only (keyword args count as one each)
                pos_inputs = [
                    inp for inp in stmt.inputs if not isinstance(inp, KeywordArg)
                ]
                kw_inputs = [inp for inp in stmt.inputs if isinstance(inp, KeywordArg)]

                if len(hint.input_types) > 0:
                    if len(stmt.inputs) != len(hint.input_types):
                        line_info = (
                            f" (line {stmt.line})" if stmt.line is not None else ""
                        )
                        errors.append(
                            f"'{stmt.func_name}'{line_info}: expected "
                            f"{len(hint.input_types)} input(s), got {len(stmt.inputs)}"
                        )
                    else:
                        # Check each input type
                        for i, (inp, expected_type) in enumerate(
                            zip(stmt.inputs, hint.input_types)
                        ):
                            actual_type = _infer_expr_type(inp, var_types)
                            if actual_type is not None:
                                if not _types_compatible(actual_type, expected_type):
                                    line_info = (
                                        f" (line {stmt.line})"
                                        if stmt.line is not None
                                        else ""
                                    )
                                    errors.append(
                                        f"'{stmt.func_name}'{line_info}: input {i} "
                                        f"expected type '{_type_str(expected_type)}', "
                                        f"got '{_type_str(actual_type)}'"
                                    )

                # Record output types
                concrete_outputs = [
                    out for out in stmt.outputs if not isinstance(out, Wildcard)
                ]
                for i, out_name in enumerate(concrete_outputs):
                    if i < len(hint.output_types):
                        var_types[out_name] = hint.output_types[i]

        case Namespace():
            _check_body(stmt.body, type_env, var_types, errors)

        case SubgraphDef():
            _check_body(stmt.body, type_env, dict(var_types), errors)

        case TryExcept():
            _check_body(stmt.try_body, type_env, var_types, errors)
            _check_body(stmt.except_body, type_env, var_types, errors)

        case TypeHintBlock():
            # Already collected by _collect_typehints; update env for later stmts
            for entry in stmt.entries:
                type_env[entry.func_name] = entry


def _type_str(t: TypeExpr) -> str:
    """Render a TypeExpr as a readable string."""
    if t.union_of:
        return " | ".join(_type_str(m) for m in t.union_of)
    if t.is_optional:
        return f"{t.name}?"
    return t.name
