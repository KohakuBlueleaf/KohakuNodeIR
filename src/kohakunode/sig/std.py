"""``kir.std``, the standard node library, and the internal ``kir.`` nodes ``expand_each`` uses."""

from typing import Any

from kohakunode.events import Event
from kohakunode.sig.library import NodeLibrary

STD = NodeLibrary("kir.std")
INTERNAL = NodeLibrary("kir")


@STD.node()
def add(a: Any, b: Any) -> Any:
    return a + b


@STD.node()
def sub(a: Any, b: Any) -> Any:
    return a - b


@STD.node()
def mul(a: Any, b: Any) -> Any:
    return a * b


@STD.node()
def div(a: Any, b: Any) -> Any:
    return a / b


@STD.node()
def floordiv(a: Any, b: Any) -> Any:
    return a // b


@STD.node()
def mod(a: Any, b: Any) -> Any:
    return a % b


@STD.node()
def neg(a: Any) -> Any:
    return -a


@STD.node()
def less(a: Any, b: Any) -> bool:
    return a < b


@STD.node()
def less_equal(a: Any, b: Any) -> bool:
    return a <= b


@STD.node()
def greater(a: Any, b: Any) -> bool:
    return a > b


@STD.node()
def greater_equal(a: Any, b: Any) -> bool:
    return a >= b


@STD.node()
def equal(a: Any, b: Any) -> bool:
    return a == b


@STD.node()
def not_equal(a: Any, b: Any) -> bool:
    return a != b


@STD.node(name="not")
def not_(a: Any) -> bool:
    return not a


@STD.node(name="and")
def and_(a: Any, b: Any) -> bool:
    return bool(a and b)


@STD.node(name="or")
def or_(a: Any, b: Any) -> bool:
    return bool(a or b)


@STD.node(name="len")
def len_(items: Any) -> int:
    return len(items)


@STD.node()
def item_at(items: Any, index: int) -> Any:
    return items[index]


@STD.node()
def append(items: list, item: Any) -> list:
    return [*items, item]


@STD.node()
def concat(a: Any, b: Any) -> Any:
    if isinstance(a, str) or isinstance(b, str):
        return f"{a}{b}"
    return a + b


@STD.node(name="range")
def range_(n: int) -> list:
    return list(range(n))


@STD.node()
def to_str(value: Any) -> str:
    return str(value)


@STD.node()
def to_int(value: Any) -> int:
    return int(value)


@STD.node()
def to_float(value: Any) -> float:
    return float(value)


@STD.node()
def identity(value: Any) -> Any:
    return value


@STD.node(ordered=True)
def print_value(value: Any) -> None:
    print(value)


@STD.node(ordered=True)
def emit(topic: str, payload: Any) -> None:
    Event.capture(topic, payload)


# Capture maintained references once. Name/structural equality alone must not
# turn a user node, signature clone, or implementation override into an event.
EMIT_SIGNATURE = STD.signatures["emit"]
EMIT_IMPL = emit


def is_standard_emit(library, signature, implementation) -> bool:
    return library is STD and signature is EMIT_SIGNATURE and implementation is EMIT_IMPL


# The collect baseline uses the same fresh-list operation without user shadowing.
INTERNAL.node("kir.collect_append")(append)


@INTERNAL.node("kir.to_list")
def to_list(items: Any) -> list:
    return list(items)


INTERNAL.node("kir.collect_items")(to_list)


@INTERNAL.node("kir.item_at", outputs=["item", "more"])
def each_item(items: list, index: int) -> tuple:
    if index < len(items):
        return items[index], True
    return None, False


@INTERNAL.node("kir.next_index")
def next_index(index: int) -> int:
    return index + 1
