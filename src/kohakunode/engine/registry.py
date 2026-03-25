import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kohakunode.ast.nodes import TypeExpr, TypeHintEntry
from kohakunode.errors import KirRuntimeError


@dataclass
class FunctionSpec:
    name: str
    func: Callable
    input_names: list[str]
    output_names: list[str]
    defaults: dict[str, Any] = field(default_factory=dict)
    input_types: list[str] | None = field(default=None)
    output_types: list[str] | None = field(default=None)


def _introspect(func: Callable) -> tuple[list[str], dict[str, Any]]:
    """Return (input_names, defaults) derived from func's signature."""
    sig = inspect.signature(func)
    input_names: list[str] = []
    defaults: dict[str, Any] = {}
    for param_name, param in sig.parameters.items():
        kind = param.kind
        if kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        input_names.append(param_name)
        if param.default is not inspect.Parameter.empty:
            defaults[param_name] = param.default
    return input_names, defaults


class Registry:
    def __init__(self) -> None:
        self._funcs: dict[str, FunctionSpec] = {}

    def register(
        self,
        name: str,
        func: Callable,
        input_names: list[str] | None = None,
        output_names: list[str] | None = None,
        defaults: dict[str, Any] | None = None,
        input_types: list[str] | None = None,
        output_types: list[str] | None = None,
    ) -> FunctionSpec:
        if name in self._funcs:
            raise KirRuntimeError(
                f"Function '{name}' is already registered",
                function_name=name,
            )

        if input_names is None or defaults is None:
            inferred_inputs, inferred_defaults = _introspect(func)
            if input_names is None:
                input_names = inferred_inputs
            if defaults is None:
                defaults = inferred_defaults

        spec = FunctionSpec(
            name=name,
            func=func,
            input_names=input_names,
            output_names=output_names if output_names is not None else [],
            defaults=defaults,
            input_types=input_types,
            output_types=output_types,
        )
        self._funcs[name] = spec
        return spec

    def lookup(self, name: str) -> FunctionSpec:
        try:
            return self._funcs[name]
        except KeyError:
            raise KirRuntimeError(
                f"Function '{name}' is not registered",
                function_name=name,
            )

    def has(self, name: str) -> bool:
        return name in self._funcs

    def unregister(self, name: str) -> None:
        if name not in self._funcs:
            raise KirRuntimeError(
                f"Cannot unregister '{name}': not registered",
                function_name=name,
            )
        del self._funcs[name]

    def list_functions(self) -> list[str]:
        return sorted(self._funcs.keys())

    def clear(self) -> None:
        self._funcs.clear()

    def generate_typehints(self) -> list[TypeHintEntry]:
        """Build TypeHintEntry objects for all functions that have type info."""
        entries: list[TypeHintEntry] = []
        for spec in self._funcs.values():
            if spec.input_types is None and spec.output_types is None:
                continue
            input_exprs = [
                TypeExpr(name=t) for t in (spec.input_types or [])
            ]
            output_exprs = [
                TypeExpr(name=t) for t in (spec.output_types or [])
            ]
            entries.append(
                TypeHintEntry(
                    func_name=spec.name,
                    input_types=input_exprs,
                    output_types=output_exprs,
                )
            )
        return entries

    def register_decorator(
        self,
        name: str | None = None,
        output_names: list[str] | None = None,
    ) -> Callable:
        def decorator(func: Callable) -> Callable:
            func_name = name if name is not None else func.__name__
            self.register(func_name, func, output_names=output_names)
            return func

        return decorator
