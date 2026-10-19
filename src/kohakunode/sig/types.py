"""Type expressions: parsing from text and Python annotations, and compatibility."""

import inspect
import types
import typing

from kohakunode.syntax.ast import ANY, TypeExpr
from kohakunode.syntax.writer import write_type

LITERAL_TYPES = {
    bool: "bool",
    int: "int",
    float: "float",
    str: "str",
    type(None): "None",
    list: "list",
    dict: "dict",
}


def parse_type(text: str) -> TypeExpr:
    """Parse the type syntax of language.md (``Image``, ``Node?``, ``list[Box]``, ``A | B``, ``_``)."""
    tokens = _tokenize(text)
    t, pos = _union(tokens, 0)
    if pos != len(tokens):
        raise ValueError(f"bad type {text!r}")
    return t


def _tokenize(text: str) -> list[str]:
    out, word = [], ""
    for ch in text:
        if ch.isalnum() or ch in "_.":
            word += ch
            continue
        if word:
            out.append(word)
            word = ""
        if ch in "[],|?":
            out.append(ch)
        elif not ch.isspace():
            raise ValueError(f"bad character {ch!r} in type {text!r}")
    if word:
        out.append(word)
    return out


def _union(tokens: list[str], pos: int) -> tuple[TypeExpr, int]:
    parts = []
    t, pos = _atom(tokens, pos)
    parts.append(t)
    while pos < len(tokens) and tokens[pos] == "|":
        t, pos = _atom(tokens, pos + 1)
        parts.append(t)
    return (parts[0] if len(parts) == 1 else TypeExpr("union", "", tuple(parts))), pos


def _atom(tokens: list[str], pos: int) -> tuple[TypeExpr, int]:
    name = tokens[pos]
    pos += 1
    if name == "_":
        return ANY, pos
    t = TypeExpr("name", name)
    if pos < len(tokens) and tokens[pos] == "[":
        args = []
        pos += 1
        while True:
            a, pos = _union(tokens, pos)
            args.append(a)
            if tokens[pos] == ",":
                pos += 1
                continue
            if tokens[pos] == "]":
                pos += 1
                break
            raise ValueError("bad generic type")
        t = TypeExpr("generic", name, tuple(args))
    if pos < len(tokens) and tokens[pos] == "?":
        t = TypeExpr("optional", "", (t,))
        pos += 1
    return t, pos


def from_annotation(annotation) -> TypeExpr:
    """Map a Python annotation to a KIR type; unknown or missing is ``_``."""
    if annotation is None or annotation is type(None):
        return TypeExpr("name", "None")
    if annotation is typing.Any or annotation is inspect.Parameter.empty:
        return ANY
    if isinstance(annotation, str):
        try:
            return parse_type(annotation)
        except ValueError:
            return ANY
    if annotation in LITERAL_TYPES:
        return TypeExpr("name", LITERAL_TYPES[annotation])
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        rest = [a for a in args if a is not type(None)]
        inner = [from_annotation(a) for a in rest]
        t = inner[0] if len(inner) == 1 else TypeExpr("union", "", tuple(inner))
        return TypeExpr("optional", "", (t,)) if len(rest) < len(args) else t
    if origin is not None:
        name = LITERAL_TYPES.get(origin, getattr(origin, "__name__", None))
        if name is None:
            return ANY
        if not args:
            return TypeExpr("name", name)
        return TypeExpr("generic", name, tuple(from_annotation(a) for a in args))
    name = getattr(annotation, "__name__", None)
    return TypeExpr("name", name) if name else ANY


def literal_type(value) -> TypeExpr:
    name = LITERAL_TYPES.get(type(value))
    return TypeExpr("name", name) if name else ANY


def _alternatives(t: TypeExpr) -> list[TypeExpr]:
    if t.kind == "union":
        return [x for a in t.args for x in _alternatives(a)]
    if t.kind == "optional":
        return _alternatives(t.args[0]) + [TypeExpr("name", "None")]
    return [t]


def fits(value: TypeExpr | None, port: TypeExpr | None) -> bool:
    """Whether a value of type ``value`` may flow into a port of type ``port``."""
    if value is None or port is None or value.kind == "any" or port.kind == "any":
        return True
    targets = _alternatives(port)
    return all(any(_fits_one(v, t) for t in targets) for v in _alternatives(value))


def _fits_one(v: TypeExpr, t: TypeExpr) -> bool:
    if v.kind == "any" or t.kind == "any":
        return True
    if v.kind == "name" and t.kind == "name":
        return v.name == t.name or (v.name == "int" and t.name == "float")
    if v.kind == "generic" and t.kind == "name":
        return v.name == t.name
    if v.kind == "name" and t.kind == "generic":
        return v.name == t.name
    if v.kind == "generic" and t.kind == "generic":
        return (
            v.name == t.name
            and len(v.args) == len(t.args)
            and all(fits(a, b) for a, b in zip(v.args, t.args))
        )
    return False


def type_text(t: TypeExpr | None) -> str:
    return "_" if t is None else write_type(t)
