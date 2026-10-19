"""``demo``: the node library the editor's run button executes against.

Every node is a small pure function with typed ports, so the sample programs
show typed, coloured wires and run end to end. Programs reach it unaliased (it
is always given to the toolchain) or through ``@use "demo" as g``.
"""

import ast
from collections.abc import Callable

from kohakunode.sig import REQUIRED, Library, Port, Signature
from kohakunode.sig.types import parse_type

DEMO = Library("demo")


def _ports(spec: str) -> tuple[Port, ...]:
    """``"a: int, b: int = 2"`` -> ports; an untyped name is ``_``."""
    out = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        head, _, default = part.partition("=")
        name, _, type_ = head.partition(":")
        out.append(
            Port(
                name.strip(),
                parse_type(type_.strip() or "_"),
                ast.literal_eval(default.strip()) if default else REQUIRED,
            )
        )
    return tuple(out)


def node(inputs: str, outputs: str = "", *, name: str | None = None, ordered: bool = False):
    """Register a function as a demo node with ports given in KIR type syntax."""

    def register(fn: Callable) -> Callable:
        DEMO.add_signature(
            Signature(
                name or fn.__name__,
                _ports(inputs),
                _ports(outputs),
                (),
                ordered,
                (fn.__doc__ or "").strip(),
            ),
            fn,
        )
        return fn

    return register


# ---------------------------------------------------------------- arithmetic


@node("a: int, b: int", "result: int")
def multiply(a, b):
    """a * b"""
    return a * b


@node("a: float, b: float", "result: float")
def divide(a, b):
    """a / b"""
    return a / b


@node("a: float, b: float", "result: float")
def min_val(a, b):
    """The smaller of a and b."""
    return min(a, b)


@node("a: float, b: float", "result: float")
def max_val(a, b):
    """The larger of a and b."""
    return max(a, b)


# ---------------------------------------------------------------- text and output


@node("n: int, r: int", "msg: str")
def format_factorial(n, r):
    """'n! = r'"""
    return f"{n}! = {r}"


@node("v", ordered=True)
def print_val(v):
    """Print a value to the run's stdout."""
    print(v)


@node("err", ordered=True)
def log_error(err):
    """Print an `@except` error value ({kind, node, message}) to the run's stdout."""
    print(f"error in {err['node']}: {err['kind']}: {err['message']}")


# ---------------------------------------------------------------- an image pipeline in miniature


@node("box: int", "fresh: bool")
def is_new(box):
    """Odd boxes are new."""
    return box % 2 == 1


@node("image: str, box: int", "crop: Crop")
def crop(image, box):
    """Cut a box out of an image; a negative box fails."""
    if box < 0:
        raise ValueError(f"box {box} is outside the image")
    return f"{image}[{box}]"


@node("crop: Crop", "node: Node")
def entity(crop):
    """Recognise the entity in a crop."""
    return f"entity({crop})"


@node("items: list", "summary: str")
def summarize(items):
    """Count the entities found."""
    found = [x for x in items if x is not None]
    return f"{len(found)} of {len(items)} boxes hold an entity"


@node("s: int", "t: int")
def finish(s):
    """s * 10"""
    return s * 10


@node("a: Node?, b: Node?, t: int, y: int", "out: list")
def combine(a, b, t, y):
    """Collect the inputs into a list."""
    return [a, b, t, y]
