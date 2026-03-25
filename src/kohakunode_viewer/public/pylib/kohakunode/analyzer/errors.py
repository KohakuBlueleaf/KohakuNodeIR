from kohakunode.errors import KirAnalysisError


class UndefinedVariableError(KirAnalysisError):
    """Raised when a variable is used before being defined."""

    def __init__(
        self,
        variable_name: str,
        line: int | None = None,
        node_context: str | None = None,
    ) -> None:
        self.variable_name = variable_name
        super().__init__(
            f"Undefined variable '{variable_name}'",
            line=line,
            node_context=node_context,
        )


class DuplicateLabelError(KirAnalysisError):
    """Raised when two namespaces share the same label in the same scope."""

    def __init__(
        self,
        label_name: str,
        first_line: int | None = None,
        duplicate_line: int | None = None,
    ) -> None:
        self.label_name = label_name
        self.first_line = first_line
        self.duplicate_line = duplicate_line
        super().__init__(
            f"Duplicate namespace label '{label_name}'",
            line=duplicate_line,
        )


class UndefinedLabelError(KirAnalysisError):
    """Raised when a branch/switch/jump references a non-existent label."""

    def __init__(
        self,
        label_name: str,
        referenced_from: str | None = None,
    ) -> None:
        self.label_name = label_name
        self.referenced_from = referenced_from
        super().__init__(
            f"Undefined namespace label '{label_name}'",
            node_context=referenced_from,
        )


class UnreachableNamespaceWarning(KirAnalysisError):
    """Indicates a namespace with no incoming jump/branch/switch/parallel."""

    def __init__(
        self,
        label_name: str,
        line: int | None = None,
    ) -> None:
        self.label_name = label_name
        super().__init__(
            f"Unreachable namespace '{label_name}' \u2014 no branch, switch, jump, or parallel targets it",
            line=line,
        )


class InvalidBuiltinArgsError(KirAnalysisError):
    """Raised when a built-in utility has wrong argument types or counts."""

    def __init__(
        self,
        builtin_name: str,
        detail: str,
        line: int | None = None,
        node_context: str | None = None,
    ) -> None:
        self.builtin_name = builtin_name
        self.detail = detail
        super().__init__(
            f"Invalid arguments for '{builtin_name}': {detail}",
            line=line,
            node_context=node_context,
        )


class WildcardInInputError(KirAnalysisError):
    """Raised when the '_' wildcard is used in input position."""

    def __init__(
        self,
        line: int | None = None,
    ) -> None:
        super().__init__(
            "Wildcard '_' can only be used in output position",
            line=line,
        )


class DuplicateSubgraphError(KirAnalysisError):
    """Raised when two @def blocks share the same name."""

    def __init__(
        self,
        name: str,
        first_line: int | None = None,
        duplicate_line: int | None = None,
    ) -> None:
        self.name = name
        self.first_line = first_line
        self.duplicate_line = duplicate_line
        super().__init__(
            f"Duplicate subgraph definition '{name}'",
            line=duplicate_line,
        )
