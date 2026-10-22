"""Define node libraries in Python with a decorator."""

import inspect
from collections.abc import Callable, Sequence

from kohakunode.sig.model import REQUIRED, Library, Port, Signature
from kohakunode.sig.records import RecordField, RecordSchema
from kohakunode.sig.types import from_annotation, parse_type
from kohakunode.syntax.ast import ANY, TypeExpr


def _port_type(t) -> TypeExpr:
    if t is None:
        return ANY
    if isinstance(t, TypeExpr):
        return t
    if isinstance(t, str):
        return parse_type(t)
    return from_annotation(t)


def signature_of(
    fn: Callable,
    name: str,
    outputs: Sequence[str] | None = None,
    output_types: Sequence | None = None,
    mutates: Sequence[str] = (),
    ordered: bool = False,
) -> Signature:
    """Build a signature from a Python function's parameters and annotations."""
    sig = inspect.signature(fn)
    inputs = []
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise TypeError(f"node {name!r}: *args / **kwargs are not node inputs")
        default = REQUIRED if p.default is p.empty else p.default
        inputs.append(Port(p.name, from_annotation(p.annotation), default))
    ret = sig.return_annotation
    if outputs is None:
        outputs = [] if ret is None or ret is type(None) else ["result"]
    if output_types is None:
        if len(outputs) == 1:
            output_types = [from_annotation(ret)]
        elif (
            ret is not sig.empty
            and getattr(ret, "__args__", None)
            and len(ret.__args__) == len(outputs)
        ):
            output_types = [from_annotation(a) for a in ret.__args__]
        else:
            output_types = [ANY] * len(outputs)
    for m in mutates:
        if m not in sig.parameters:
            raise TypeError(f"node {name!r}: mutates names unknown input {m!r}")
    return Signature(
        name,
        tuple(inputs),
        tuple(Port(o, _port_type(t)) for o, t in zip(outputs, output_types)),
        tuple(mutates),
        ordered,
        inspect.getdoc(fn) or "",
    )


class NodeLibrary(Library):
    """A library whose nodes are Python functions.

    >>> lib = NodeLibrary("demo")
    >>> @lib.node(outputs=["total"])
    ... def add(a: int, b: int) -> int:
    ...     return a + b
    """

    def __init__(self, name: str):
        super().__init__(name)

    def record(self, name: str, fields: Sequence[RecordField | tuple]) -> RecordSchema:
        """Register a record from ordered ``(name, type[, default])`` fields.

        A three-item tuple supplies a default even when that default is None.
        RecordField instances can be mixed with tuple specifications.
        """
        parsed = []
        for spec in fields:
            if isinstance(spec, RecordField):
                parsed.append(spec)
            elif isinstance(spec, tuple) and len(spec) in (2, 3):
                parsed.append(
                    RecordField(
                        spec[0],
                        _port_type(spec[1]),
                        len(spec) == 3,
                        spec[2] if len(spec) == 3 else None,
                    )
                )
            else:
                raise ValueError("record fields must be RecordField or (name, type[, default])")
        return self.add_record(name, parsed)

    def node(
        self,
        name: str | None = None,
        *,
        outputs: Sequence[str] | None = None,
        output_types: Sequence | None = None,
        mutates: Sequence[str] = (),
        ordered: bool = False,
    ):
        def register(fn: Callable) -> Callable:
            self.add_signature(
                signature_of(fn, name or fn.__name__, outputs, output_types, mutates, ordered), fn
            )
            return fn

        return register

    def add(
        self,
        name: str,
        fn: Callable,
        *,
        inputs: Sequence[str | tuple] | None = None,
        outputs: Sequence[str] = ("result",),
        mutates: Sequence[str] = (),
        ordered: bool = False,
    ) -> None:
        """Register ``fn`` under explicit port names; inputs are passed as keywords.

        Each input is a name or ``(name, type)`` / ``(name, type, default)``.
        Without ``inputs`` the function's own signature is used.
        """
        if inputs is None:
            self.add_signature(signature_of(fn, name, outputs, None, mutates, ordered), fn)
            return
        ports = []
        for spec in inputs:
            if isinstance(spec, str):
                ports.append(Port(spec))
            else:
                ports.append(
                    Port(spec[0], _port_type(spec[1]), spec[2] if len(spec) > 2 else REQUIRED)
                )
        sig = Signature(
            name, tuple(ports), tuple(Port(o) for o in outputs), tuple(mutates), ordered
        )
        self.add_signature(sig, fn)
