"""The node library the basic examples call (the names v1's examples used)."""

from typing import Any

from kohakunode import NodeLibrary

LIB = NodeLibrary("basics")


@LIB.node()
def add(a: Any, b: Any) -> Any:
    return a + b


@LIB.node()
def subtract(a: Any, b: Any) -> Any:
    return a - b


@LIB.node()
def multiply(a: Any, b: Any) -> Any:
    return a * b


@LIB.node()
def divide(a: float, b: float) -> float:
    return a / b if b != 0 else 0


@LIB.node()
def min_val(a: Any, b: Any) -> Any:
    return min(a, b)


@LIB.node()
def max_val(a: Any, b: Any) -> Any:
    return max(a, b)


@LIB.node()
def less_than(a: Any, b: Any) -> bool:
    return a < b


@LIB.node()
def less_equal(a: Any, b: Any) -> bool:
    return a <= b


@LIB.node()
def greater_than(a: Any, b: Any) -> bool:
    return a > b


@LIB.node()
def to_float(value: Any) -> float:
    return float(value)


@LIB.node()
def to_string(value: Any) -> str:
    return str(value)


@LIB.node()
def concat(a: Any, b: Any) -> str:
    return f"{a}{b}"


@LIB.node()
def format_string(template: str, value: Any) -> str:
    return template.format(value)


@LIB.node()
def format_factorial(n: int, r: int) -> str:
    return f"{n}! = {r}"


@LIB.node(name="print", ordered=True)
def print_(value: Any) -> None:
    print(value)


@LIB.node(ordered=True)
def print_val(value: Any) -> None:
    print(value)


@LIB.node(outputs=["data"])
def load_csv(path: str) -> list:
    """A stand-in for reading a file: 200 numbers."""
    return list(range(200))


@LIB.node(outputs=["cleaned"])
def clean_data(data: list) -> list:
    return [x for x in data if x >= 0]


@LIB.node(outputs=["filtered"])
def filter_outliers(data: list, threshold: float = 0.5) -> list:
    return data[: int(len(data) * threshold)]


@LIB.node(outputs=["mean", "std", "count"])
def compute_stats(data: list) -> tuple:
    mean = sum(data) / len(data)
    std = (sum((x - mean) ** 2 for x in data) / len(data)) ** 0.5
    return mean, std, len(data)


@LIB.node(outputs=["normalized"])
def normalize(data: list, mean: float, std: float) -> list:
    return [(x - mean) / std for x in data] if std else data


@LIB.node(ordered=True)
def save_csv(data: list, path: str) -> None:
    print(f"[save_csv] {len(data)} rows -> {path}")
