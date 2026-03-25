"""Top-level executor for KohakuNodeIR.

Orchestrates parsing, validation, compilation, and interpretation in a single
coherent pipeline.  This is the primary user-facing entry point for running
KIR programs.

Public API
----------
Executor          -- class that holds shared state (registry, compiler) across runs
run(source, ...)  -- one-shot convenience function for source strings
run_file(path, ...)  -- one-shot convenience function for source files
"""

import pathlib
from collections.abc import Callable
from typing import Any

from kohakunode.analyzer.validator import validate_or_raise
from kohakunode.ast.nodes import Program
from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.engine.context import VariableStore
from kohakunode.engine.backend import ExecutionBackend
from kohakunode.engine.interpreter import Interpreter
from kohakunode.engine.registry import Registry
from kohakunode.parser.parser import parse, parse_file


class Executor:
    """Orchestrates the full KIR execution pipeline.

    Parameters
    ----------
    registry:
        The function registry to use.  A fresh, empty ``Registry`` is created
        when *registry* is ``None``.
    validate:
        When ``True`` (the default), ``validate_or_raise`` is called before
        compilation.  Set to ``False`` to skip semantic validation entirely
        (useful for trusted, pre-validated programs).
    """

    def __init__(
        self,
        registry: Registry | None = None,
        validate: bool = True,
        backend: ExecutionBackend | None = None,
    ) -> None:
        self.registry: Registry = registry if registry is not None else Registry()
        self.validate: bool = validate
        self.backend: ExecutionBackend | None = backend
        self._compiler: DataflowCompiler = DataflowCompiler()

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def execute(self, program: Program) -> VariableStore:
        """Execute a parsed KIR ``Program`` AST.

        Steps
        -----
        1. Validate — if *self.validate* is ``True``, run ``validate_or_raise``.
           Errors raise; warnings are collected and ignored here.
        2. Compile  — run the dataflow compiler pass.  This is a no-op when
           ``program.mode`` is not ``"dataflow"``.
        3. Interpret — create an ``Interpreter`` and run the (possibly
           reordered) program to completion.

        Parameters
        ----------
        program:
            The root ``Program`` AST node to execute.

        Returns
        -------
        VariableStore
            The interpreter's variable store after execution completes.
            Callers can inspect final variable state via ``VariableStore.get``
            or ``VariableStore.snapshot``.
        """
        if self.validate:
            validate_or_raise(program)

        program = self._compiler.transform(program)

        interpreter = Interpreter(self.registry, backend=self.backend)
        interpreter.run(program)
        return interpreter.context.variables

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def execute_source(self, source: str) -> VariableStore:
        """Parse *source* and execute it.

        Parameters
        ----------
        source:
            A KIR source string.

        Returns
        -------
        VariableStore
            The variable store after execution.
        """
        return self.execute(parse(source))

    def execute_file(self, path: str | pathlib.Path) -> VariableStore:
        """Read a KIR source file, parse it, and execute it.

        Parameters
        ----------
        path:
            Path to a ``.kir`` file (``str`` or ``pathlib.Path``).

        Returns
        -------
        VariableStore
            The variable store after execution.
        """
        return self.execute(parse_file(path))

    # ------------------------------------------------------------------
    # Registry delegation
    # ------------------------------------------------------------------

    def register(self, name: str, func: Callable, **kwargs: Any) -> "Executor":
        """Register a Python callable under *name* in the executor's registry.

        All extra keyword arguments are forwarded to ``Registry.register``.

        Returns
        -------
        Executor
            ``self``, enabling method chaining.
        """
        self.registry.register(name, func, **kwargs)
        return self

    def register_decorator(self, **kwargs: Any) -> Callable:
        """Return a decorator that registers the decorated function.

        All keyword arguments are forwarded to ``Registry.register_decorator``.

        Example
        -------
        ::

            executor = Executor()

            @executor.register_decorator(name="add", output_names=["result"])
            def add(a, b):
                return a + b
        """
        return self.registry.register_decorator(**kwargs)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def run(
    source: str,
    registry: Registry | None = None,
    validate: bool = True,
    backend: ExecutionBackend | None = None,
) -> VariableStore:
    """Parse and execute a KIR source string in a single call.

    Parameters
    ----------
    source:
        A KIR source string.
    registry:
        Optional pre-populated ``Registry``.  A fresh one is created when
        ``None``.
    validate:
        When ``True`` (the default), semantic validation runs before
        compilation.

    Returns
    -------
    VariableStore
        The variable store after execution.
    """
    return Executor(
        registry=registry, validate=validate, backend=backend
    ).execute_source(source)


def run_file(
    path: str | pathlib.Path,
    registry: Registry | None = None,
    validate: bool = True,
    backend: ExecutionBackend | None = None,
) -> VariableStore:
    """Parse and execute a KIR source file in a single call.

    Parameters
    ----------
    path:
        Path to a ``.kir`` file (``str`` or ``pathlib.Path``).
    registry:
        Optional pre-populated ``Registry``.  A fresh one is created when
        ``None``.
    validate:
        When ``True`` (the default), semantic validation runs before
        compilation.

    Returns
    -------
    VariableStore
        The variable store after execution.
    """
    return Executor(registry=registry, validate=validate, backend=backend).execute_file(
        path
    )
