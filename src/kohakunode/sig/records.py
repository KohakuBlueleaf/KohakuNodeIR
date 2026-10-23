"""Immutable, portable record schemas; independent of signatures and runtime values."""

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, replace
from typing import Any

from kohakunode._dataclass import stateful_dataclass
from kohakunode.syntax.ast import ANY, TypeExpr

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_RESERVED = frozenset({"_", "True", "False", "None"})
SCALAR_TYPES = frozenset({"bool", "int", "float", "str", "None"})
CONTAINER_TYPES = frozenset({"list", "dict"})


def check_name(name: str, what: str = "name") -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name) or name in _RESERVED:
        raise ValueError(f"invalid record {what}: {name!r}")


def _ensure_new(value, attribute: str) -> None:
    if hasattr(value, attribute):
        raise FrozenInstanceError(f"cannot reinitialize {type(value).__name__}")


def _reject_state(self, state) -> None:
    raise FrozenInstanceError(f"cannot overwrite {type(self).__name__} state")


@stateful_dataclass(frozen=True, slots=True, init=False)
class FrozenList:
    """An immutable JSON array, distinct from tuples in the runtime value domain."""

    items: tuple

    def __init__(self, items: tuple) -> None:
        _ensure_new(self, "items")
        object.__setattr__(self, "items", tuple(_freeze(item, set()) for item in items))

    def __reduce__(self):
        return FrozenList, (self.items,)

    __setstate__ = _reject_state


@stateful_dataclass(frozen=True, slots=True, init=False)
class FrozenDict:
    """An immutable JSON object retaining insertion order."""

    items: tuple[tuple[str, Any], ...]

    def __init__(self, items: tuple[tuple[str, Any], ...]) -> None:
        _ensure_new(self, "items")
        items = tuple(items)
        if any(type(key) is not str for key, _ in items):
            raise ValueError("record default object keys must be strings")
        if len({key for key, _ in items}) != len(items):
            raise ValueError("record default object keys must be unique")
        object.__setattr__(self, "items", tuple((key, _freeze(item, set())) for key, item in items))

    def __reduce__(self):
        return FrozenDict, (self.items,)

    __setstate__ = _reject_state


def freeze_default(value: Any) -> Any:
    """Copy a portable JSON default into a deeply immutable, pickle-safe value."""
    return _freeze(value, set())


def _freeze(value: Any, active: set[int]) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("record defaults must contain only finite JSON numbers")
        return value
    if type(value) in (FrozenList, FrozenDict):
        return value
    if type(value) not in (list, dict):
        raise ValueError("record defaults must be JSON; nested record defaults are unsupported")
    if id(value) in active:
        raise ValueError("record defaults cannot be cyclic")
    active.add(id(value))
    try:
        if isinstance(value, list):
            return FrozenList(tuple(_freeze(item, active) for item in value))
        if any(type(key) is not str for key in value):
            raise ValueError("record default object keys must be strings")
        return FrozenDict(tuple((key, _freeze(item, active)) for key, item in value.items()))
    finally:
        active.remove(id(value))


def thaw_default(value: Any) -> Any:
    """Return a fresh JSON value from a frozen schema default."""
    if isinstance(value, FrozenList):
        return [thaw_default(item) for item in value.items]
    if isinstance(value, FrozenDict):
        return {key: thaw_default(item) for key, item in value.items}
    return value


def portable_default_equal(left: Any, right: Any) -> bool:
    """Compare portable defaults without Python's bool/int/float equality coercion."""
    try:
        return json.dumps(
            thaw_default(freeze_default(left)), sort_keys=True, allow_nan=False
        ) == json.dumps(thaw_default(freeze_default(right)), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return False


def validate_type(type_: TypeExpr) -> None:
    if (
        type(type_) is not TypeExpr
        or type(type_.kind) is not str
        or type(type_.name) is not str
        or type(type_.args) is not tuple
    ):
        raise ValueError("record field type must be an immutable TypeExpr")
    if type_.kind == "any":
        valid = not type_.name and not type_.args
    elif type_.kind == "name":
        valid = not type_.args and bool(type_.name)
        if valid and type_.name not in SCALAR_TYPES | CONTAINER_TYPES:
            for part in type_.name.split("."):
                check_name(part, "type name")
    elif type_.kind == "optional":
        valid = not type_.name and len(type_.args) == 1
    elif type_.kind == "union":
        valid = not type_.name and len(type_.args) >= 2
    elif type_.kind == "generic":
        valid = (type_.name == "list" and len(type_.args) == 1) or (
            type_.name == "dict"
            and len(type_.args) == 2
            and type_.args[0] == TypeExpr("name", "str")
        )
    else:
        valid = False
    if not valid:
        raise ValueError(f"unsupported record field type {type_!r}")
    for arg in type_.args:
        validate_type(arg)


def normalize_type(type_: TypeExpr) -> TypeExpr:
    """Normalize programmatically built types to the signature text grammar.

    In particular `_?` and nested optional/union expressions have no lossless
    spelling in that grammar. Normalize them before schema identity is fixed.
    """
    args = tuple(normalize_type(arg) for arg in type_.args)
    if type_.kind == "optional":
        inner = args[0]
        if inner.kind in ("any", "optional") or inner == TypeExpr("name", "None"):
            return inner
        if inner.kind == "union":
            return normalize_type(TypeExpr("union", "", inner.args + (TypeExpr("name", "None"),)))
    if type_.kind == "union":
        parts = []
        for arg in args:
            for part in arg.args if arg.kind == "union" else (arg,):
                if part not in parts:
                    parts.append(part)
        return parts[0] if len(parts) == 1 else TypeExpr("union", "", tuple(parts))
    return TypeExpr(type_.kind, type_.name, args)


def default_fits(value: Any, type_: TypeExpr) -> bool:
    """Strict JSON default checking; nominal record defaults are never implicit dicts."""
    if type_.kind == "any":
        return True
    if type_.kind == "optional":
        return value is None or default_fits(value, type_.args[0])
    if type_.kind == "union":
        return any(default_fits(value, arg) for arg in type_.args)
    if type_.kind == "generic":
        if type_.name == "list":
            return isinstance(value, list) and all(default_fits(v, type_.args[0]) for v in value)
        return isinstance(value, dict) and all(
            default_fits(k, type_.args[0]) and default_fits(v, type_.args[1])
            for k, v in value.items()
        )
    return {
        "bool": type(value) is bool,
        "int": type(value) is int,
        "float": type(value) in (int, float),
        "str": type(value) is str,
        "None": value is None,
        "list": type(value) is list,
        "dict": type(value) is dict,
    }.get(type_.name, False)


@stateful_dataclass(frozen=True, slots=True, init=False)
class RecordField:
    name: str
    type: TypeExpr = ANY
    has_default: bool = False
    default: Any = None

    def __init__(
        self, name: str, type: TypeExpr = ANY, has_default: bool = False, default: Any = None
    ) -> None:
        _ensure_new(self, "name")
        check_name(name, "field name")
        validate_type(type)
        type = normalize_type(type)
        if has_default is not True and has_default is not False:
            raise ValueError("record has_default must be a boolean")
        if not has_default and default is not None:
            raise ValueError("record field default requires has_default=True")
        frozen = freeze_default(default) if has_default else None
        if has_default and not default_fits(thaw_default(frozen), type):
            raise ValueError(f"default of record field {name!r} does not match its type")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "has_default", has_default)
        object.__setattr__(self, "default", frozen)

    def __reduce__(self):
        return RecordField, (self.name, self.type, self.has_default, self.default)

    __setstate__ = _reject_state


@stateful_dataclass(frozen=True, slots=True, init=False)
class RecordSchema:
    name: str
    fields: tuple[RecordField, ...]
    schema_id: str = ""

    def __init__(self, name: str, fields: tuple[RecordField, ...], schema_id: str = "") -> None:
        _ensure_new(self, "name")
        check_name(name, "schema name")
        if name in SCALAR_TYPES | CONTAINER_TYPES:
            raise ValueError(f"record name {name!r} conflicts with a built-in type")
        fields = tuple(fields)
        if not all(type(field) is RecordField for field in fields):
            raise ValueError("record fields must be RecordField instances")
        if len({field.name for field in fields}) != len(fields):
            raise ValueError(f"duplicate fields in record {name!r}")
        if not isinstance(schema_id, str):
            raise ValueError("record schema_id must be a string")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "schema_id", schema_id)

    def __reduce__(self):
        return RecordSchema, (self.name, self.fields, self.schema_id)

    __setstate__ = _reject_state

    def field(self, name: str) -> RecordField | None:
        return next((field for field in self.fields if field.name == name), None)


def record_schema_equal(left: RecordSchema, right: RecordSchema) -> bool:
    """Type-sensitive schema compatibility for environment identity checks."""
    if type(left) is not RecordSchema or type(right) is not RecordSchema:
        return False
    if (left.name, left.schema_id, len(left.fields)) != (
        right.name,
        right.schema_id,
        len(right.fields),
    ):
        return False
    return all(
        (a.name, a.type, a.has_default) == (b.name, b.type, b.has_default)
        and (not a.has_default or portable_default_equal(a.default, b.default))
        for a, b in zip(left.fields, right.fields)
    )


def qualify_type(type_: TypeExpr, library: str) -> TypeExpr:
    name = type_.name
    if type_.kind == "name" and name not in SCALAR_TYPES | CONTAINER_TYPES and "." not in name:
        name = f"{library}.{name}"
    return TypeExpr(type_.kind, name, tuple(qualify_type(arg, library) for arg in type_.args))


def qualify_schema(schema: RecordSchema, library: str) -> RecordSchema:
    if not isinstance(library, str) or not library:
        raise ValueError("record library must have a nonempty nominal name")
    for part in library.split("."):
        check_name(part, "library name")
    canonical = f"{library}.{schema.name}"
    if schema.schema_id and schema.schema_id != canonical:
        raise ValueError(f"record schema identity must be {canonical!r}")
    return replace(
        schema,
        schema_id=canonical,
        fields=tuple(
            replace(field, type=qualify_type(field.type, library)) for field in schema.fields
        ),
    )


def nominal_references(type_: TypeExpr) -> set[str]:
    refs = set()
    if type_.kind == "name" and type_.name not in SCALAR_TYPES | CONTAINER_TYPES:
        refs.add(type_.name)
    for arg in type_.args:
        refs.update(nominal_references(arg))
    return refs


def validate_record_cycles(records: Mapping[str, RecordSchema]) -> None:
    """Reject cycles among known schemas, including optional/container references."""
    by_id = {schema.schema_id: schema for schema in records.values()}
    active, done = set(), set()

    def visit(schema_id: str) -> None:
        if schema_id in active:
            raise ValueError(f"recursive record schema {schema_id!r}")
        if schema_id in done or schema_id not in by_id:
            return
        active.add(schema_id)
        for field in by_id[schema_id].fields:
            for ref in nominal_references(field.type):
                visit(ref)
        active.remove(schema_id)
        done.add(schema_id)

    for schema_id in by_id:
        visit(schema_id)


def generated_names(schema: RecordSchema) -> tuple[str, ...]:
    return (f"{schema.name}.make",) + tuple(
        f"{schema.name}.{kind}.{field.name}" for field in schema.fields for kind in ("get", "with")
    )


def record_schema(name: str, fields: Sequence[RecordField]) -> RecordSchema:
    """Build a schema from ordered fields without binding a library identity yet."""
    return RecordSchema(name, tuple(fields))
