from typing import Optional


class KirError(Exception):
    """Base class for all KohakuNodeIR errors."""

    pass


class KirSyntaxError(KirError):
    """Raised during parsing when bad syntax is encountered in .kir files."""

    def __init__(
        self,
        message: str,
        line: Optional[int] = None,
        column: Optional[int] = None,
        source_line: Optional[str] = None,
    ) -> None:
        self.message = message
        self.line = line
        self.column = column
        self.source_line = source_line
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = [self.message]
        if self.line is not None and self.column is not None:
            parts.append(f" (line {self.line}, col {self.column})")
        elif self.line is not None:
            parts.append(f" (line {self.line})")
        if self.source_line is not None:
            parts.append(f"\n  {self.source_line}")
        return "".join(parts)


class KirAnalysisError(KirError):
    """Raised during static analysis (scope resolution, variable checks, etc.)."""

    def __init__(
        self,
        message: str,
        line: Optional[int] = None,
        node_context: Optional[str] = None,
    ) -> None:
        self.message = message
        self.line = line
        self.node_context = node_context
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = [self.message]
        if self.line is not None:
            parts.append(f" (line {self.line})")
        if self.node_context is not None:
            parts.append(f" [node: {self.node_context}]")
        return "".join(parts)


class KirRuntimeError(KirError):
    """Raised during execution of a KohakuNodeIR program."""

    def __init__(
        self,
        message: str,
        line: Optional[int] = None,
        function_name: Optional[str] = None,
    ) -> None:
        self.message = message
        self.line = line
        self.function_name = function_name
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = [self.message]
        if self.line is not None:
            parts.append(f" (line {self.line})")
        if self.function_name is not None:
            parts.append(f" [in function: {self.function_name}]")
        return "".join(parts)


class KirCompilationError(KirError):
    """Raised during IR-to-IR compilation (e.g. dataflow to sequential lowering)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message
