"""Execution wrapper with output capture for print/display nodes.

Provides ``ExecutionSession`` which installs special print/display node
implementations that record their outputs, then runs the KIR program via the
standard Executor pipeline.
"""

from __future__ import annotations

import json
from typing import Any

from kohakunode.engine.executor import Executor
from kohakunode.engine.registry import Registry
from kohakunode.errors import KirError


class ExecutionSession:
    """Run a KIR program while capturing print/display output.

    A *session* clones the print/display registrations so that every call
    appends to ``self.outputs``.  The caller can inspect this list after
    execution to relay messages to the client.
    """

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.outputs: list[dict[str, Any]] = []
        self._setup_capture_nodes()

    # ------------------------------------------------------------------
    # Capture nodes
    # ------------------------------------------------------------------

    def _setup_capture_nodes(self) -> None:
        """Override print/display in the registry to capture output."""
        # Unregister existing implementations (if any) so we can re-register.
        for name in ("print", "display"):
            if self.registry.has(name):
                self.registry.unregister(name)

        def captured_print(value: Any) -> None:
            self.outputs.append({"type": "output", "value": str(value)})

        def captured_display(value: Any) -> Any:
            self.outputs.append({"type": "output", "value": repr(value)})
            return value  # pass-through

        self.registry.register("print", captured_print, output_names=[])
        self.registry.register("display", captured_display, output_names=["pass"])

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, kir_source: str) -> dict[str, Any]:
        """Parse and execute *kir_source*, returning a result dict."""
        self.outputs = []
        try:
            executor = Executor(registry=self.registry, validate=True)
            variables = executor.execute_source(kir_source)
            return {
                "success": True,
                "variables": _serialise_snapshot(variables.snapshot()),
                "output": self.outputs,
            }
        except (KirError, Exception) as exc:  # noqa: BLE001
            return {
                "success": False,
                "error": str(exc),
                "output": self.outputs,
            }


def _serialise_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Ensure every value in the snapshot is JSON-serialisable."""
    result: dict[str, Any] = {}
    for key, value in snapshot.items():
        try:
            json.dumps(value)
            result[key] = value
        except (TypeError, ValueError):
            result[key] = repr(value)
    return result
