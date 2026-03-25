"""Pluggable execution backend for KIR function dispatch.

The Interpreter walks the AST and handles control flow. The backend
handles how registered functions are actually called. This separation
enables caching, state management, logging, distributed execution, etc.
"""

import abc
import hashlib
import pickle
from dataclasses import dataclass, field
from typing import Any, Callable

from kohakunode.ast.nodes import FuncCall
from kohakunode.engine.registry import FunctionSpec


@dataclass(frozen=True)
class NodeInvocation:
    """Everything the backend needs to invoke a single function call."""

    spec: FunctionSpec
    call_kwargs: dict[str, Any]
    node: FuncCall
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def node_id(self) -> str | None:
        return self.metadata.get("node_id")


class ExecutionBackend(abc.ABC):
    """Abstract base for execution backends.

    Override `invoke` to control how registered functions are called.
    """

    @abc.abstractmethod
    def invoke(self, invocation: NodeInvocation) -> Any:
        """Call the function and return its result."""
        ...

    def on_node_enter(self, invocation: NodeInvocation) -> None:
        """Called before invoke. Override for side effects."""

    def on_node_exit(
        self, invocation: NodeInvocation, result: Any, error: Exception | None
    ) -> None:
        """Called after invoke (or after error). Override for side effects."""


class DefaultBackend(ExecutionBackend):
    """Direct function call -- the original behavior."""

    def invoke(self, invocation: NodeInvocation) -> Any:
        return invocation.spec.func(**invocation.call_kwargs)


class CachingBackend(ExecutionBackend):
    """Caches results keyed by (func_name, input_hash).

    Skips execution when inputs are identical to a previous call.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], Any] = {}

    def invoke(self, invocation: NodeInvocation) -> Any:
        key = self._make_key(invocation)
        if key in self._cache:
            return self._cache[key]
        result = invocation.spec.func(**invocation.call_kwargs)
        self._cache[key] = result
        return result

    def invalidate(self, func_name: str | None = None) -> None:
        """Clear cache. If func_name given, only that function."""
        if func_name is None:
            self._cache.clear()
        else:
            self._cache = {k: v for k, v in self._cache.items() if k[0] != func_name}

    @staticmethod
    def _make_key(invocation: NodeInvocation) -> tuple[str, str]:
        name = invocation.spec.name
        h = hashlib.sha256(name.encode())
        for k in sorted(invocation.call_kwargs):
            h.update(k.encode())
            try:
                h.update(pickle.dumps(invocation.call_kwargs[k]))
            except (pickle.PicklingError, TypeError):
                h.update(str(id(invocation.call_kwargs[k])).encode())
        return (name, h.hexdigest())
