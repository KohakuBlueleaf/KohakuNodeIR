"""The KIR abstract syntax tree.

Every statement carries ``meta`` (from ``@meta``), ``hint`` (from ``@hint``) and
the source ``line``. Optional ``origin`` records source provenance separately from
editor metadata. Equality ignores ``line`` and ``origin`` so trees from different
texts of the same program compare equal.
"""

from dataclasses import FrozenInstanceError, dataclass, field
from typing import Any

# ---------------------------------------------------------------- types


@dataclass(frozen=True, slots=True, init=False)
class TypeExpr:
    """A type: ``kind`` is "any", "name", "optional", "generic" or "union"."""

    kind: str
    name: str = ""
    args: tuple["TypeExpr", ...] = ()

    def __init__(self, kind: str, name: str = "", args: tuple["TypeExpr", ...] = ()) -> None:
        if hasattr(self, "kind"):
            raise FrozenInstanceError("cannot reinitialize TypeExpr")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "args", args)

    def __reduce__(self):
        return TypeExpr, (self.kind, self.name, self.args)

    def __setstate__(self, state) -> None:
        raise FrozenInstanceError("cannot overwrite TypeExpr state")


ANY = TypeExpr("any")

# ---------------------------------------------------------------- expressions


@dataclass(frozen=True)
class Name:
    id: str


@dataclass(frozen=True)
class Literal:
    value: Any


Expr = Name | Literal


@dataclass(frozen=True)
class Arg:
    """A call input: positional when ``key`` is None."""

    value: Expr
    key: str | None = None


# ---------------------------------------------------------------- statements


@dataclass(frozen=True)
class Origin:
    """Source provenance, including the call sites that generated a statement."""

    module: str
    node_id: str
    line: int | None = None
    definition: str | None = None
    calls: tuple["Origin", ...] = ()
    generated: str | None = None


@dataclass(eq=False)
class Stmt:
    meta: dict = field(default_factory=dict, kw_only=True)
    hint: dict = field(default_factory=dict, kw_only=True)
    line: int | None = field(default=None, kw_only=True)
    origin: Origin | None = field(default=None, kw_only=True, compare=False)

    def _key(self) -> tuple:
        return tuple(
            getattr(self, f) for f in self.__dataclass_fields__ if f not in ("line", "origin")
        )

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self._key() == other._key()

    def __hash__(self) -> int:
        return id(self)


@dataclass(eq=False)
class Assign(Stmt):
    target: str
    value: Expr
    type: TypeExpr | None = None


@dataclass(eq=False)
class Call(Stmt):
    """``(args)name(outs)``; an output of None is the discard ``_``."""

    name: str
    args: list[Arg]
    outs: list[str | None]


@dataclass(eq=False)
class Branch(Stmt):
    cond: Expr
    true_label: str
    false_label: str


@dataclass(eq=False)
class Switch(Stmt):
    value: Expr
    cases: list[tuple[Any, str]]
    default: str | None = None


@dataclass(eq=False)
class Jump(Stmt):
    label: str


@dataclass(eq=False)
class Parallel(Stmt):
    labels: list[str]


@dataclass(eq=False)
class Each(Stmt):
    """``(items)each(item[, index], `label`)``; None outputs are ``_``."""

    items: Expr
    item: str | None
    index: str | None
    label: str
    has_index: bool = False


@dataclass(eq=False)
class Namespace(Stmt):
    label: str
    body: list[Stmt]


@dataclass(eq=False)
class Dataflow(Stmt):
    body: list[Stmt]


@dataclass(eq=False)
class Try(Stmt):
    body: list[Stmt]
    handler: list[Stmt]
    error_name: str | None = None


@dataclass(frozen=True)
class Param:
    name: str
    type: TypeExpr | None = None
    default: Expr | None = None


@dataclass(frozen=True)
class OutParam:
    name: str
    type: TypeExpr | None = None


@dataclass(eq=False)
class Def(Stmt):
    name: str
    params: list[Param]
    outputs: list[OutParam]
    body: list[Stmt]


@dataclass(frozen=True)
class TypeHintEntry:
    name: str
    inputs: tuple[TypeExpr, ...]
    outputs: tuple[TypeExpr, ...]


@dataclass(eq=False)
class TypeHints(Stmt):
    entries: list[TypeHintEntry]


@dataclass(frozen=True)
class Use:
    library: str
    alias: str | None = None


@dataclass(frozen=True)
class Import:
    module: str
    alias: str


@dataclass
class Program:
    uses: list[Use] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)
    mode: str | None = None
    imports: list[Import] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)


BUILTINS = frozenset({"branch", "switch", "jump", "parallel", "each"})


def walk(stmts: list[Stmt]):
    """Yield every statement, depth first, including nested bodies."""
    for s in stmts:
        yield s
        for body in children(s):
            yield from walk(body)


def children(s: Stmt) -> list[list[Stmt]]:
    match s:
        case Namespace() | Dataflow() | Def():
            return [s.body]
        case Try():
            return [s.body, s.handler]
    return []


def labels_entered(s: Stmt) -> list[str]:
    """The namespace labels a builtin statement names."""
    match s:
        case Branch():
            return [s.true_label, s.false_label]
        case Switch():
            return [label for _, label in s.cases] + ([s.default] if s.default else [])
        case Jump():
            return [s.label]
        case Parallel():
            return list(s.labels)
        case Each():
            return [s.label]
    return []


def reads(s: Stmt) -> list[str]:
    """Names a simple or builtin statement reads."""
    match s:
        case Assign(value=Name(id=n)):
            return [n]
        case Call():
            return [a.value.id for a in s.args if isinstance(a.value, Name)]
        case Branch(cond=Name(id=n)) | Switch(value=Name(id=n)) | Each(items=Name(id=n)):
            return [n]
    return []


def writes(s: Stmt) -> list[str]:
    """Names a simple or builtin statement writes."""
    match s:
        case Assign():
            return [s.target]
        case Call():
            return [o for o in s.outs if o is not None]
        case Each():
            return [n for n in (s.item, s.index) if n is not None]
    return []
