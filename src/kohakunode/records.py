"""Closed, immutable runtime records and explicit portable adapter encodings.

Only exact built-in portable values are accepted. Record fields are stored as
private frozen containers; projection never reflects over arbitrary host objects.
"""

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from kohakunode.sig.records import RecordSchema, thaw_default
from kohakunode.syntax.ast import TypeExpr


def _initialize_container(container, items: tuple) -> None:
    try:
        _ = container.items
    except AttributeError:
        object.__setattr__(container, "items", items)
    else:
        raise TypeError("immutable record storage cannot be reinitialized")


@dataclass(frozen=True, slots=True, init=False)
class _FrozenList:
    items: tuple

    def __init__(self, items: tuple) -> None:
        _initialize_container(self, items)

    def __setstate__(self, state) -> None:
        raise TypeError("immutable record storage cannot be replaced")


@dataclass(frozen=True, slots=True, init=False)
class _FrozenDict:
    items: tuple[tuple[str, Any], ...]

    def __init__(self, items: tuple) -> None:
        _initialize_container(self, items)

    def __setstate__(self, state) -> None:
        raise TypeError("immutable record storage cannot be replaced")


def _freeze(value: Any, active: set[int]) -> Any:
    if value is None or type(value) in (bool, int, str, RecordValue):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("record values require finite floats")
        return value
    if type(value) not in (list, dict):
        raise TypeError("record values require exact portable scalars, lists, dicts or records")
    if id(value) in active:
        raise ValueError("record values cannot contain cycles")
    active.add(id(value))
    try:
        if type(value) is list:
            return _FrozenList(tuple(_freeze(item, active) for item in value))
        if any(type(key) is not str for key in value):
            raise TypeError("record dictionaries require exact string keys")
        return _FrozenDict(tuple((key, _freeze(value[key], active)) for key in sorted(value)))
    finally:
        active.remove(id(value))


def _thaw(value: Any) -> Any:
    if type(value) is _FrozenList:
        return [_thaw(item) for item in value.items]
    if type(value) is _FrozenDict:
        return {key: _thaw(item) for key, item in value.items}
    return value


def _matches(value: Any, type_: TypeExpr) -> bool:
    if type_.kind == "any":
        return True
    if type_.kind == "optional":
        return value is None or _matches(value, type_.args[0])
    if type_.kind == "union":
        return any(_matches(value, option) for option in type_.args)
    if type_.kind == "generic":
        if type_.name == "list":
            return type(value) is _FrozenList and all(
                _matches(item, type_.args[0]) for item in value.items
            )
        return type(value) is _FrozenDict and all(
            _matches(key, type_.args[0]) and _matches(item, type_.args[1])
            for key, item in value.items
        )
    name = type_.name
    if name == "None":
        return value is None
    if name == "float":
        return type(value) in (int, float)
    builtins = {"bool": bool, "int": int, "str": str, "list": _FrozenList, "dict": _FrozenDict}
    if name in builtins:
        return type(value) is builtins[name]
    return type(value) is RecordValue and value.schema_id == name


def _check_schema(schema: RecordSchema) -> None:
    if type(schema) is not RecordSchema:
        raise TypeError("expected an exact RecordSchema")
    if type(schema.schema_id) is not str or not schema.schema_id:
        raise ValueError("record schema must have a canonical schema_id before construction")


def _snapshot_fields(schema: RecordSchema, values: dict) -> tuple:
    _check_schema(schema)
    declared = {item.name for item in schema.fields}
    if set(values) - declared:
        raise TypeError(f"unknown fields for {schema.schema_id}: {sorted(set(values) - declared)}")
    result = []
    for item in schema.fields:
        if item.name in values:
            value = values[item.name]
        elif item.has_default:
            value = thaw_default(item.default)
        else:
            raise TypeError(f"missing required field {schema.schema_id}.{item.name}")
        frozen = _freeze(value, set())
        if not _matches(frozen, item.type):
            raise TypeError(f"field {schema.schema_id}.{item.name} does not match {item.type!r}")
        result.append((item.name, frozen))
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True, init=False, eq=False)
class RecordValue:
    """A validated nominal record; construct with ``RecordValue(schema, **fields)``.

    ``construct`` is the equivalent functional API. Fields are not Python object
    attributes: use ``project(schema, value, field)`` or ``value[field]``. Mutable
    projections are fresh copies; nested records can be shared because they are
    immutable. Pickle is supported for trusted process transport, not adapter input.
    """

    schema_id: str
    _fields: tuple = field(repr=False)
    _schema: RecordSchema = field(repr=False)

    def __init__(self, schema: RecordSchema, /, **fields: Any) -> None:
        try:
            _ = self._fields
        except AttributeError:
            pass
        else:
            raise TypeError("an immutable RecordValue cannot be reinitialized")
        frozen = _snapshot_fields(schema, fields)
        object.__setattr__(self, "schema_id", schema.schema_id)
        object.__setattr__(self, "_fields", frozen)
        object.__setattr__(self, "_schema", schema)

    def __getitem__(self, name: str) -> Any:
        return project(self._schema, self, name)

    def __eq__(self, other: object) -> bool:
        return type(other) is RecordValue and _canonical(self) == _canonical(other)

    def __hash__(self) -> int:
        return hash(self.__togeari_digest__())

    def __togeari_digest__(self) -> bytes:
        """SHA-256 of ``kohakunode.record.v1\\0`` plus typed, length-delimited data.

        Integers use signed hexadecimal and floats use ``float.hex``; strings use
        UTF-8 with surrogatepass. Container counts delimit ordered values; fields
        and dictionary keys are sorted. This supports arbitrary-size integers
        without changing Python's global decimal-string conversion limits.
        """
        return hashlib.sha256(b"kohakunode.record.v1\0" + _canonical(self)).digest()

    def __setstate__(self, state) -> None:
        raise TypeError("immutable records must be restored through validated construction")

    def __reduce__(self):
        values = {name: _thaw(value) for name, value in self._fields}
        return _restore_record, (self._schema, values)


def construct(schema: RecordSchema, /, **fields: Any) -> RecordValue:
    """Snapshot and validate all fields; missing is distinct from explicit ``None``."""
    return RecordValue(schema, **fields)


def _restore_record(schema: RecordSchema, fields: dict) -> RecordValue:
    return construct(schema, **fields)


def _check_record(schema: RecordSchema, record: RecordValue) -> dict:
    _check_schema(schema)
    if type(record) is not RecordValue:
        raise TypeError("expected an exact RecordValue, not a host object or record subclass")
    if record.schema_id != schema.schema_id:
        raise TypeError(f"expected record {schema.schema_id}, got {record.schema_id}")
    values = dict(record._fields)
    if set(values) != {item.name for item in schema.fields}:
        raise TypeError(f"record field shape does not match {schema.schema_id}")
    for item in schema.fields:
        if not _matches(values[item.name], item.type):
            raise TypeError(f"record field {schema.schema_id}.{item.name} has the wrong type")
    return values


def _check_field(schema: RecordSchema, name: str) -> None:
    if type(name) is not str:
        raise TypeError("record field name must be an exact string")
    if schema.field(name) is None:
        raise KeyError(f"unknown field {schema.schema_id}.{name}")


def project(schema: RecordSchema, record: RecordValue, field: str) -> Any:
    """Read only validated record storage, materializing fresh lists and dictionaries."""
    values = _check_record(schema, record)
    _check_field(schema, field)
    return _thaw(values[field])


def replace_field(schema: RecordSchema, record: RecordValue, field: str, value: Any) -> RecordValue:
    """Return a validated snapshot with one replacement, leaving the original untouched."""
    values = _check_record(schema, record)
    _check_field(schema, field)
    fields = {name: _thaw(item) for name, item in values.items()}
    fields[field] = value
    return construct(schema, **fields)


@dataclass(frozen=True)
class RecordOperation:
    """Pickle-safe callable descriptor behind generated make/get/with signatures."""

    schema: RecordSchema
    kind: str
    field: str | None = None

    def __post_init__(self) -> None:
        _check_schema(self.schema)
        if self.kind not in ("make", "get", "with"):
            raise ValueError("record operation kind must be make, get or with")
        if self.kind == "make":
            if self.field is not None:
                raise ValueError("make operation cannot name a field")
        else:
            _check_field(self.schema, self.field)

    def __call__(self, /, *args: Any, **kwargs: Any) -> Any:
        names = (
            [item.name for item in self.schema.fields]
            if self.kind == "make"
            else ["record"] if self.kind == "get" else ["record", "value"]
        )
        if len(args) > len(names):
            raise TypeError("too many positional inputs for record operation")
        values = dict(kwargs)
        for name, value in zip(names, args):
            if name in values:
                raise TypeError(f"multiple values for record input {name!r}")
            values[name] = value
        if self.kind == "make":
            return construct(self.schema, **values)
        if set(values) != set(names):
            raise TypeError(f"{self.kind} operation requires inputs {names}")
        if self.kind == "get":
            return project(self.schema, values["record"], self.field)
        return replace_field(self.schema, values["record"], self.field, values["value"])


def _encode(value: Any) -> Any:
    if type(value) is RecordValue:
        return {
            "$kir": "record",
            "schema": value.schema_id,
            "fields": {name: _encode(item) for name, item in value._fields},
        }
    if type(value) is _FrozenList:
        return {"$kir": "list", "items": [_encode(item) for item in value.items]}
    if type(value) is _FrozenDict:
        return {"$kir": "dict", "items": {key: _encode(item) for key, item in value.items}}
    return value


def encode_portable(value: Any) -> Any:
    """Snapshot exact portable scalars, containers and records into tagged data.

    Every container has an explicit tag, so application dictionaries cannot
    impersonate records. This performs no attribute/property conversion of host
    objects and does not change process-wide JSON integer limits.
    """
    return _encode(_freeze(value, set()))


def encode_record(record: RecordValue) -> dict:
    """Encode records and every nested container with explicit collision-safe tags.

    Scalars remain native values, including arbitrary-size integers. An external
    JSON transport may impose its own integer/string conversion limits; this
    codec and the record digest do not change those process-wide settings.
    """
    if type(record) is not RecordValue:
        raise TypeError("encode_record requires an exact RecordValue")
    return _encode(record)


def _canonical(record: RecordValue) -> bytes:
    parts: list[bytes] = []
    _canonical_parts(record, parts)
    return b"".join(parts)


def _canonical_parts(value: Any, parts: list[bytes]) -> None:
    if value is None:
        parts.append(b"n")
        return
    if type(value) is bool:
        parts.append(b"b1" if value else b"b0")
        return
    if type(value) is int:
        tag, data = b"i", format(value, "x").encode("ascii")
    elif type(value) is float:
        tag, data = b"f", value.hex().encode("ascii")
    elif type(value) is str:
        tag, data = b"s", value.encode("utf-8", "surrogatepass")
    else:
        if type(value) is RecordValue:
            items = value._fields
            parts.append(b"r" + str(len(items)).encode("ascii") + b":")
            _canonical_parts(value.schema_id, parts)
        elif type(value) is _FrozenDict:
            items = value.items
            parts.append(b"d" + str(len(items)).encode("ascii") + b":")
        else:
            parts.append(b"l" + str(len(value.items)).encode("ascii") + b":")
            for item in value.items:
                _canonical_parts(item, parts)
            return
        for key, item in items:
            _canonical_parts(key, parts)
            _canonical_parts(item, parts)
        return
    parts.extend((tag, str(len(data)).encode("ascii"), b":", data))


def _decode(data: Any, schemas: Mapping[str, RecordSchema], active: set[int]) -> Any:
    if data is None or type(data) in (bool, int, str):
        return data
    if type(data) is float:
        if not math.isfinite(data):
            raise ValueError("encoded record values require finite floats")
        return data
    if type(data) is not dict:
        raise TypeError("encoded containers require exact tagged dictionaries")
    if id(data) in active:
        raise ValueError("encoded record values cannot contain cycles")
    active.add(id(data))
    try:
        if any(type(key) is not str for key in data):
            raise TypeError("encoded dictionary keys must be exact strings")
        tag = data.get("$kir")
        if type(tag) is not str or tag not in ("record", "list", "dict"):
            raise ValueError("unknown or missing record codec tag")
        expected = {"$kir", "schema", "fields"} if tag == "record" else {"$kir", "items"}
        if set(data) != expected:
            raise ValueError("invalid tagged record codec shape")
        if tag == "list":
            items = data["items"]
            if type(items) is not list:
                raise TypeError("encoded list items must be an exact list")
            return [_decode(item, schemas, active) for item in items]
        items = data["fields"] if tag == "record" else data["items"]
        if type(items) is not dict or any(type(key) is not str for key in items):
            raise TypeError("encoded fields/items must be an exact string-keyed dictionary")
        if tag == "dict":
            return {key: _decode(value, schemas, active) for key, value in items.items()}
        schema_id = data["schema"]
        if type(schema_id) is not str or schema_id not in schemas:
            raise ValueError("unknown record schema ID")
        schema = schemas[schema_id]
        _check_schema(schema)
        if schema.schema_id != schema_id:
            raise ValueError("schema registry key does not match canonical schema ID")
        if set(items) != {item.name for item in schema.fields}:
            raise ValueError("encoded record must contain exactly its schema fields")
        return construct(
            schema, **{key: _decode(value, schemas, active) for key, value in items.items()}
        )
    finally:
        active.remove(id(data))


def decode_portable(data: Any, schemas: Mapping[str, RecordSchema] | None = None) -> Any:
    """Decode tagged portable data; a registry is needed only for record tags."""
    return _decode(data, {} if schemas is None else schemas, set())


def decode_record(data: Any, schemas: Mapping[str, RecordSchema]) -> RecordValue:
    """Decode explicit adapter data using a registry keyed by canonical schema ID.

    Unknown schemas, extra/missing fields, malformed tags, nonportable values and
    type mismatches are rejected. No Python classes are loaded from the payload.
    """
    result = _decode(data, schemas, set())
    if type(result) is not RecordValue:
        raise TypeError("decode_record requires a tagged record at the top level")
    return result
