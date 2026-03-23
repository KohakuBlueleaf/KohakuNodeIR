from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------


@dataclass
class ASTNode:
    line: int | None = field(default=None, kw_only=True)


@dataclass
class Expression(ASTNode):
    pass


@dataclass
class Statement(ASTNode):
    pass


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


@dataclass
class Identifier(Expression):
    name: str = field(default="")


@dataclass
class Literal(Expression):
    value: Any = field(default=None)
    # literal_type is one of: "int", "float", "str", "bool", "none", "list", "dict"
    literal_type: str = field(default="none")


@dataclass
class KeywordArg(Expression):
    name: str = field(default="")
    value: Expression = field(default_factory=lambda: Identifier())


@dataclass
class LabelRef(Expression):
    """Backtick-quoted label reference, e.g. `my_label`."""

    name: str = field(default="")


# ---------------------------------------------------------------------------
# Other nodes
# ---------------------------------------------------------------------------


@dataclass
class Wildcard(ASTNode):
    """The `_` discard symbol."""

    pass


@dataclass
class MetaAnnotation(ASTNode):
    """@meta key=value pairs attached to a statement."""

    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Parameter(ASTNode):
    """A parameter in a @def signature."""

    name: str = field(default="")
    default: Expression | None = field(default=None)


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


@dataclass
class Assignment(Statement):
    target: str = field(default="")
    value: Expression = field(default_factory=lambda: Identifier())
    metadata: list[MetaAnnotation] | None = field(default=None)


@dataclass
class FuncCall(Statement):
    inputs: list[Expression] = field(default_factory=list)
    func_name: str = field(default="")
    outputs: list[str | Wildcard] = field(default_factory=list)
    metadata: list[MetaAnnotation] | None = field(default=None)


@dataclass
class Namespace(Statement):
    name: str = field(default="")
    body: list[Statement] = field(default_factory=list)


@dataclass
class SubgraphDef(Statement):
    name: str = field(default="")
    params: list[Parameter] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    body: list[Statement] = field(default_factory=list)


@dataclass
class DataflowBlock(Statement):
    """@dataflow: scoped block -- execution order resolved by data dependencies."""

    body: list[Statement] = field(default_factory=list)


@dataclass
class ModeDecl(Statement):
    mode: str = field(default="")


# ---------------------------------------------------------------------------
# Built-in utility call statements
# ---------------------------------------------------------------------------


@dataclass
class Branch(Statement):
    """(cond)branch(`t`, `f`) — conditional branch."""

    condition: Expression = field(default_factory=lambda: Identifier())
    true_label: str = field(default="")
    false_label: str = field(default="")
    metadata: list[MetaAnnotation] | None = field(default=None)


@dataclass
class Switch(Statement):
    """(val)switch(v1=>`l1`, ...) — multi-way branch."""

    value: Expression = field(default_factory=lambda: Identifier())
    cases: list[tuple[Expression, str]] = field(default_factory=list)
    default_label: str | None = field(default=None)
    metadata: list[MetaAnnotation] | None = field(default=None)


@dataclass
class Jump(Statement):
    """()jump(`label`) — unconditional jump."""

    target: str = field(default="")
    metadata: list[MetaAnnotation] | None = field(default=None)


@dataclass
class Parallel(Statement):
    """()parallel(`l1`, `l2`, ...) — fork parallel branches."""

    labels: list[str] = field(default_factory=list)
    metadata: list[MetaAnnotation] | None = field(default=None)


# ---------------------------------------------------------------------------
# Root node
# ---------------------------------------------------------------------------


@dataclass
class Program(ASTNode):
    """Root node of a KohakuNodeIR program."""

    body: list[Statement] = field(default_factory=list)
    # mode is "dataflow" or None
    mode: str | None = field(default=None)
