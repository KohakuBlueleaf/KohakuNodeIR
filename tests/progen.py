"""Seeded random KIR programs over a tiny node library, for property checks.

Programs only read names written on every path before the read, loops are
bounded, and ``flaky`` fails for some inputs, so `@try` paths run too.
"""

import random

from kohakunode import NodeLibrary

LIB = NodeLibrary("gen")


@LIB.node()
def inc(x: int) -> int:
    return x + 1


@LIB.node()
def mix(a: int, b: int) -> int:
    return (a * 3 + b) % 101


@LIB.node()
def small(x: int) -> bool:
    return x % 3 != 0


@LIB.node()
def flaky(x: int) -> int:
    if x % 4 == 1:
        raise ValueError(f"flaky({x})")
    return x * 2


@LIB.node()
def total(xs: list) -> int:
    return sum(v for v in xs if isinstance(v, int))


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.n_names = 0
        self.n_labels = 0
        self.n_defs = 0
        self.defs: list[tuple[str, int]] = []
        self.lines: list[str] = []

    def name(self) -> str:
        self.n_names += 1
        return f"v{self.n_names}"

    def label(self, base: str) -> str:
        self.n_labels += 1
        return f"{base}{self.n_labels}"

    def operand(self, defined: list[str]) -> str:
        if defined and self.r.random() < 0.8:
            return self.r.choice(defined)
        return str(self.r.randint(0, 20))

    def emit(self, depth: int, text: str) -> None:
        self.lines.append("    " * depth + text)

    def block(self, depth: int, defined: list[str], budget: int) -> list[str]:
        """Emit statements; return the names defined on every path through them."""
        defined = list(defined)
        for _ in range(self.r.randint(1, 4)):
            if budget <= 0:
                break
            budget -= 1
            kind = self.r.choice(
                ["assign", "call", "call", "branch", "each", "loop", "try", "dataflow", "def"]
                if depth < 3
                else ["assign", "call", "call"]
            )
            getattr(self, KINDS[kind])(depth, defined, budget)
        return defined

    def assign(self, depth, defined, budget):
        n = self.name() if not defined or self.r.random() < 0.6 else self.r.choice(defined)
        self.emit(depth, f"{n} = {self.r.randint(0, 9)}")
        if n not in defined:
            defined.append(n)

    def call(self, depth, defined, budget):
        n = self.name() if not defined or self.r.random() < 0.6 else self.r.choice(defined)
        if self.defs and self.r.random() < 0.3:
            fname, arity = self.r.choice(self.defs)
            args = ", ".join(self.operand(defined) for _ in range(arity))
            self.emit(depth, f"({args}){fname}({n})")
        elif self.r.random() < 0.5:
            self.emit(depth, f"({self.operand(defined)})inc({n})")
        else:
            self.emit(depth, f"({self.operand(defined)}, {self.operand(defined)})mix({n})")
        if n not in defined:
            defined.append(n)

    def branch(self, depth, defined, budget):
        c = self.name()  # a bool: kept out of `defined`
        self.emit(depth, f"({self.operand(defined)})small({c})")
        yes, no = self.label("yes"), self.label("no")
        self.emit(depth, f"({c})branch(`{yes}`, `{no}`)")
        self.emit(depth, f"{yes}:")
        a = self.block(depth + 1, defined, budget // 2)
        self.emit(depth, f"{no}:")
        b = self.block(depth + 1, defined, budget // 2)
        defined[:] = [x for x in a if x in b]

    def each(self, depth, defined, budget):
        # The list names stay out of `defined`: every node here takes ints.
        items = self.name()
        self.emit(depth, f"{items} = {[self.r.randint(0, 9) for _ in range(self.r.randint(0, 4))]}")
        acc = self.name()
        self.emit(depth, f"{acc} = []")
        body = self.label("body")
        item = self.name()
        self.emit(depth, f"({items})each({item}, `{body}`)")
        self.emit(depth, f"{body}:")
        inner = self.block(depth + 1, [*defined, item], budget // 2)
        self.emit(depth + 1, f"({acc}, {self.r.choice(inner)})append({acc})")

    def loop(self, depth, defined, budget):
        i = self.name()
        self.emit(depth, f"{i} = 0")
        defined.append(i)
        top, again, done = self.label("loop"), self.label("again"), self.label("done")
        self.emit(depth, f"()jump(`{top}`)")
        self.emit(depth, f"{top}:")
        self.block(depth + 1, defined, budget // 2)
        self.emit(depth + 1, f"({i})inc({i})")
        more = self.name()
        self.emit(depth + 1, f"({i}, {self.r.randint(1, 3)})less({more})")
        self.emit(depth + 1, f"({more})branch(`{again}`, `{done}`)")
        self.emit(depth + 1, f"{again}:")
        self.emit(depth + 2, f"()jump(`{top}`)")
        self.emit(depth + 1, f"{done}:")

    def try_(self, depth, defined, budget):
        out = self.name()
        self.emit(depth, f"{out} = -1")
        defined.append(out)
        self.emit(depth, "@try:")
        self.block(depth + 1, defined, budget // 2)
        self.emit(depth + 1, f"({self.operand(defined)})flaky({out})")
        err = self.name()
        self.emit(depth, f"@except {err}:")
        self.emit(depth + 1, f"{out} = 99")

    def dataflow(self, depth, defined, budget):
        self.emit(depth, "@dataflow:")
        a, b = self.name(), self.name()
        self.emit(depth + 1, f"({a}, {self.operand(defined)})mix({b})")
        self.emit(depth + 1, f"({self.operand(defined)})inc({a})")
        defined += [a, b]

    def def_(self, depth, defined, budget):
        if depth != 0:
            return self.call(depth, defined, budget)
        self.n_defs += 1
        fname = f"f{self.n_defs}"
        arity = self.r.randint(1, 2)
        params = [f"p{k}" for k in range(arity)]
        start = len(self.lines)
        self.emit(0, f"@def ({', '.join(params)}){fname}(out):")
        inner = self.block(1, params, 3)
        self.emit(1, f"({self.r.choice(inner)}, {params[0]})mix(out)")
        self.lines.append("")
        # Definitions go first in the file; move this one to the front.
        body = self.lines[start:]
        del self.lines[start:]
        self.lines[0:0] = body
        self.defs.append((fname, arity))


KINDS = {k: k for k in ("assign", "call", "branch", "each", "loop", "dataflow")} | {
    "try": "try_",
    "def": "def_",
}


def program(seed: int) -> str:
    g = Gen(seed)
    defined = g.block(0, [], 10)
    g.emit(
        0, f"({', '.join(defined[-2:] or ['0'])})mix(result)" if len(defined) >= 2 else "result = 0"
    )
    return "\n".join(g.lines) + "\n"
