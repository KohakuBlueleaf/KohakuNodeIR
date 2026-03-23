from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kohakunode.ast.nodes import Statement
from kohakunode.errors import KirRuntimeError


class VariableStore:
    """Flat, unscoped variable store shared across the entire execution."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        if name not in self._store:
            raise KirRuntimeError(f"Undefined variable: '{name}'")
        return self._store[name]

    def set(self, name: str, value: Any) -> None:
        self._store[name] = value

    def has(self, name: str) -> bool:
        return name in self._store

    def snapshot(self) -> dict:
        return dict(self._store)


@dataclass
class ExecutionFrame:
    """One level of the execution stack, representing a statement list being iterated."""

    statements: list[Statement]
    position: int = field(default=0)
    namespace_name: str | None = field(default=None)


class ExecutionContext:
    """
    Manages all mutable state during execution of a KohakuNodeIR program.

    The frame stack mirrors the namespace entry/exit model:
    - Top-level statements live in the bottom-most frame.
    - Entering a namespace (via branch/switch/jump/parallel) pushes a new frame.
    - When a frame is exhausted execution pops back to the parent frame, which
      continues from wherever it was left off.

    Variable scope is intentionally flat: every set() call writes into the
    single shared VariableStore, regardless of the current frame depth.
    """

    def __init__(self) -> None:
        self.variables: VariableStore = VariableStore()
        self._frame_stack: list[ExecutionFrame] = []

    # ------------------------------------------------------------------
    # Frame stack management
    # ------------------------------------------------------------------

    def push_frame(
        self,
        statements: list[Statement],
        namespace_name: str | None = None,
    ) -> None:
        """Push a new execution frame onto the stack."""
        self._frame_stack.append(
            ExecutionFrame(statements=statements, namespace_name=namespace_name)
        )

    def pop_frame(self) -> None:
        """Pop the current (topmost) frame, returning control to the parent."""
        if not self._frame_stack:
            raise KirRuntimeError("Cannot pop frame: execution stack is empty")
        self._frame_stack.pop()

    @property
    def current_frame(self) -> ExecutionFrame:
        """Return the topmost frame. Raises if the stack is empty."""
        if not self._frame_stack:
            raise KirRuntimeError("No active execution frame")
        return self._frame_stack[-1]

    @property
    def has_frames(self) -> bool:
        """True when there is at least one frame on the stack."""
        return bool(self._frame_stack)

    # ------------------------------------------------------------------
    # Statement access and advancement
    # ------------------------------------------------------------------

    @property
    def current_statement(self) -> Statement | None:
        """
        Return the statement at the current position in the active frame,
        or None if the frame is exhausted.
        """
        frame = self.current_frame
        if frame.position >= len(frame.statements):
            return None
        return frame.statements[frame.position]

    def advance(self) -> None:
        """Move the position pointer forward by one in the current frame."""
        self.current_frame.position += 1

    @property
    def is_frame_exhausted(self) -> bool:
        """True when the current frame's position has moved past its last statement."""
        frame = self.current_frame
        return frame.position >= len(frame.statements)
