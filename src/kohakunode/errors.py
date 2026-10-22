"""Exceptions raised by the KIR toolchain."""


class KirError(Exception):
    """Base class for every KIR error."""


class KirSyntaxError(KirError):
    def __init__(self, message: str, line: int | None = None, column: int | None = None):
        self.line = line
        self.column = column
        where = f" (line {line}, column {column})" if line is not None else ""
        super().__init__(f"{message}{where}")


class KirCheckError(KirError):
    """A program failed the checker; ``diagnostics`` holds every finding."""

    def __init__(self, diagnostics: list):
        self.diagnostics = diagnostics
        errors = [d for d in diagnostics if d.severity == "error"]
        super().__init__("\n".join(str(d) for d in errors))


class KirSignatureError(KirError):
    """A signature file or `@use` library could not be loaded."""


class KirGraphError(KirError):
    """A graph view (.kirgraph) is malformed."""


class KirRuntimeError(KirError):
    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"{message} (line {line})" if line is not None else message)


class NodeFailure(KirRuntimeError):
    """A node call raised; carries the original exception for `@except`."""

    def __init__(self, node: str, error: BaseException, line: int | None = None, *, origin=None):
        self.node = node
        self.error = error
        self.origin = origin
        super().__init__(f"node {node!r} failed: {type(error).__name__}: {error}", line)
