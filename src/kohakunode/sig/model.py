"""Node signatures and libraries."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kohakunode.syntax.ast import ANY, TypeExpr

REQUIRED = object()  # default of an input that must be given


@dataclass(frozen=True)
class Port:
    name: str
    type: TypeExpr = ANY
    default: Any = REQUIRED

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


@dataclass(frozen=True)
class Signature:
    name: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    mutates: tuple[str, ...] = ()
    ordered: bool = False
    doc: str = ""

    def input(self, name: str) -> Port | None:
        return next((p for p in self.inputs if p.name == name), None)


@dataclass
class Library:
    """Named signatures, plus implementations when the library was built in Python."""

    name: str
    signatures: dict[str, Signature] = field(default_factory=dict)
    impls: dict[str, Callable] = field(default_factory=dict)

    def __contains__(self, node: str) -> bool:
        return node in self.signatures

    def add_signature(self, sig: Signature, impl: Callable | None = None) -> None:
        if sig.name in self.signatures:
            raise ValueError(f"library {self.name!r} already has a node {sig.name!r}")
        self.signatures[sig.name] = sig
        if impl is not None:
            self.impls[sig.name] = impl
