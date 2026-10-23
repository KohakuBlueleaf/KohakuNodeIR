"""Semantic event snapshots, independent of scheduling and event delivery transports.

Payloads are explicitly tagged portable data, not ordinary application dicts.
Use ``Event.capture`` for application values and ``to_dict`` for detached wire
representations. Record schemas are needed only for optional decoding.
"""

import math
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from typing import Any

from kohakunode._dataclass import stateful_dataclass
from kohakunode.records import decode_portable, encode_portable
from kohakunode.sig.records import (
    FrozenDict,
    FrozenList,
    RecordSchema,
    freeze_default,
    thaw_default,
)


def _validate_encoded(value: Any, active: set[int]) -> None:
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("event payload numbers must be finite")
        return
    if type(value) is not dict:
        raise TypeError("encoded event containers require tagged dictionaries")
    if id(value) in active:
        raise ValueError("event payload cannot contain cycles")
    active.add(id(value))
    try:
        if any(type(key) is not str for key in value):
            raise TypeError("event payload keys must be exact strings")
        tag = value.get("$kir")
        if type(tag) is not str or tag not in ("record", "list", "dict"):
            raise ValueError("unknown or missing event payload tag")
        expected = {"$kir", "schema", "fields"} if tag == "record" else {"$kir", "items"}
        if set(value) != expected:
            raise ValueError("invalid encoded event payload shape")
        if tag == "record" and (type(value["schema"]) is not str or not value["schema"]):
            raise ValueError("encoded event record requires a schema ID")
        items = value["fields"] if tag == "record" else value["items"]
        if tag == "list":
            if type(items) is not list:
                raise TypeError("encoded event list items must be a list")
            children = items
        else:
            if type(items) is not dict or any(type(key) is not str for key in items):
                raise TypeError("encoded event fields/items must be a string-keyed dictionary")
            children = items.values()
        for child in children:
            _validate_encoded(child, active)
    finally:
        active.remove(id(value))


def _key(value):
    """A typed immutable key, without bool/int coercion or JSON integer limits."""
    if type(value) is FrozenList:
        return ("list", tuple(_key(item) for item in value.items))
    if type(value) is FrozenDict:
        return ("dict", tuple(sorted((key, _key(item)) for key, item in value.items)))
    if type(value) is float:
        return ("float", value.hex())
    return (type(value).__name__, value)


@stateful_dataclass(frozen=True, slots=True, init=False, eq=False)
class Event:
    """A committed reference event: topic and immutable **encoded** payload.

    ``Event(topic, encoded_payload)`` accepts the tagged transport form.
    ``Event.capture(topic, application_value)`` snapshots an application value.
    Neither operation delivers anything to a consumer.
    """

    topic: str
    payload: Any

    def __init__(self, topic: str, encoded_payload: Any) -> None:
        if hasattr(self, "topic"):
            raise FrozenInstanceError("cannot reinitialize Event")
        if type(topic) is not str:
            raise TypeError("event topic must be an exact string")
        _validate_encoded(encoded_payload, set())
        frozen = freeze_default(encoded_payload)
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "payload", frozen)

    @classmethod
    def capture(cls, topic: str, payload: Any) -> "Event":
        return cls(topic, encode_portable(payload))

    def to_dict(self) -> dict:
        """Return a detached transport mapping; mutating it cannot change this event."""
        return {"topic": self.topic, "payload": thaw_default(self.payload)}

    def decode(self, schemas: Mapping[str, RecordSchema] | None = None) -> Any:
        """Materialize fresh application values; record tags require a schema registry."""
        return decode_portable(thaw_default(self.payload), schemas)

    def __eq__(self, other: object) -> bool:
        return type(other) is Event and (self.topic, _key(self.payload)) == (
            other.topic,
            _key(other.payload),
        )

    def __hash__(self) -> int:
        return hash((self.topic, _key(self.payload)))

    def __reduce__(self):
        return Event, (self.topic, thaw_default(self.payload))

    def __setstate__(self, state) -> None:
        raise FrozenInstanceError("cannot overwrite Event state")
