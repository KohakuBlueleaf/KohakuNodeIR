"""Seeded random KIR programs over a tiny node library, for property checks.

Programs only read names written on every path before the read, loops are
bounded, and ``flaky`` fails for some inputs, so `@try` paths run too.

``program(seed)`` gives a top-level program. ``entry_program(seed)`` gives a
program whose job is an entry `@def` with parameters and defaults, and adds
`switch`, `parallel`, `ordered` and `mutates` nodes (with aliases), `each`
with an exit `jump`, nested `each` and `@try` around `each`: the shapes an
executor that runs statements out of order must get right.
"""

import random
from dataclasses import dataclass, field

from kohakunode.sig.library import NodeLibrary

LIB = NodeLibrary("gen")

# Calls of the ordered node ``emit``, in call order; executors compare it.
EFFECTS: list[int] = []


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


@LIB.node()
def pick(x: int) -> int:
    return x % 3


@LIB.node(ordered=True)
def emit(x: int) -> int:
    EFFECTS.append(x)
    return x


@LIB.node(mutates=["box"])
def bump(box: list, x: int) -> None:
    box.append(x)


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.n_names = 0
        self.n_labels = 0
        self.n_defs = 0
        self.defs: list[tuple[str, int]] = []
        self.lines: list[str] = []
        # Loop counters while their body is generated: readable, never a target.
        self.fixed: set[str] = set()

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

    def target(self, defined: list[str]) -> str:
        """A new name, or (40%) an existing one that is not a running loop's counter."""
        targets = [x for x in defined if x not in self.fixed]
        return self.name() if not targets or self.r.random() < 0.6 else self.r.choice(targets)

    def emit(self, depth: int, text: str) -> None:
        self.lines.append("    " * depth + text)

    def kinds(self, depth: int) -> list[str]:
        if depth < 3:
            return ["assign", "call", "call", "branch", "each", "loop", "try", "dataflow", "def"]
        return ["assign", "call", "call"]

    def block(self, depth: int, defined: list[str], budget: int) -> list[str]:
        """Emit statements; return the names defined on every path through them."""
        defined = list(defined)
        for _ in range(self.r.randint(1, 4)):
            if budget <= 0:
                break
            budget -= 1
            kind = self.r.choice(self.kinds(depth))
            getattr(self, KINDS[kind])(depth, defined, budget)
        return defined

    def assign(self, depth, defined, budget):
        n = self.target(defined)
        self.emit(depth, f"{n} = {self.r.randint(0, 9)}")
        if n not in defined:
            defined.append(n)

    def call(self, depth, defined, budget):
        n = self.target(defined)
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

        # The body reads the counter but never writes it, so the loop ends.
        self.fixed.add(i)
        self.block(depth + 1, defined, budget // 2)
        self.fixed.discard(i)
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


class EntryGen(Gen):
    """Programs whose job is the entry `@def main`, with every control shape."""

    def kinds(self, depth: int) -> list[str]:
        if depth < 4:
            return [
                "assign",
                "call",
                "call",
                "branch",
                "each",
                "loop",
                "try",
                "dataflow",
                "switch",
                "parallel",
                "ordered",
                "mutate",
                "each_exit",
                "try_each",
            ]
        return ["assign", "call", "call", "ordered"]

    def ordered(self, depth, defined, budget):
        n = self.name()
        self.emit(depth, f"({self.operand(defined)})emit({n})")
        defined.append(n)

    def switch(self, depth, defined, budget):
        v = self.name()  # an int in 0..2: kept out of `defined`
        self.emit(depth, f"({self.operand(defined)})pick({v})")
        labels = [self.label("case") for _ in range(3)]
        self.emit(depth, f"({v})switch(0=>`{labels[0]}`, 1=>`{labels[1]}`, _=>`{labels[2]}`)")
        common = None
        for lab in labels:
            self.emit(depth, f"{lab}:")
            got = self.block(depth + 1, defined, budget // 3)
            common = got if common is None else [x for x in common if x in got]
        defined[:] = common

    def parallel(self, depth, defined, budget):
        a, b = self.label("arm"), self.label("arm")
        self.emit(depth, f"()parallel(`{a}`, `{b}`)")
        self.emit(depth, f"{a}:")
        first = self.block(depth + 1, defined, budget // 2)
        self.emit(depth, f"{b}:")
        self.block(depth + 1, first, budget // 2)
        # Arms run in listed order, so the first arm's names are written before the second.
        defined[:] = first

    def mutate(self, depth, defined, budget):
        box, alias, t = self.name(), self.name(), self.name()
        self.emit(depth, f"{box} = [{self.r.randint(0, 9)}]")
        self.emit(depth, f"{alias} = {box}")
        self.emit(depth, f"({alias})total({t})")
        self.emit(depth, f"({box}, {self.operand(defined)})bump()")
        t2 = self.name()
        self.emit(depth, f"({alias})total({t2})")
        defined += [t, t2]

    def each_exit(self, depth, defined, budget):
        items = self.name()
        self.emit(depth, f"{items} = {[self.r.randint(0, 9) for _ in range(self.r.randint(1, 5))]}")
        acc = self.name()
        self.emit(depth, f"{acc} = []")
        body, keep, stop, out = (self.label(x) for x in ("body", "keep", "stop", "out"))
        item, c = self.name(), self.name()
        self.emit(depth, f"({items})each({item}, `{body}`)")
        self.emit(depth, f"{body}:")
        self.emit(depth + 1, f"({item})small({c})")
        self.emit(depth + 1, f"({c})branch(`{keep}`, `{stop}`)")
        self.emit(depth + 1, f"{keep}:")
        inner = self.block(depth + 2, [*defined, item], budget // 2)
        self.emit(depth + 2, f"({acc}, {self.r.choice(inner)})append({acc})")
        self.emit(depth + 1, f"{stop}:")
        self.emit(depth + 2, f"()jump(`{out}`)")
        self.emit(depth, f"{out}:")
        self.emit(depth + 1, f"({acc})total({self.name()})")
        n = self.name()
        self.emit(depth, f"({acc})total({n})")
        defined.append(n)

    def try_each(self, depth, defined, budget):
        out = self.name()
        self.emit(depth, f"{out} = -1")
        defined.append(out)
        self.emit(depth, "@try:")
        items, acc, item, body = self.name(), self.name(), self.name(), self.label("body")
        self.emit(
            depth + 1, f"{items} = {[self.r.randint(0, 9) for _ in range(self.r.randint(1, 4))]}"
        )
        self.emit(depth + 1, f"{acc} = []")
        self.emit(depth + 1, f"({items})each({item}, `{body}`)")
        self.emit(depth + 1, f"{body}:")
        self.emit(depth + 2, f"({item})flaky({self.name()})")
        self.emit(depth + 2, f"({acc}, {item})append({acc})")
        self.emit(depth + 1, f"({acc})total({out})")
        self.emit(depth, f"@except {self.name()}:")
        self.emit(depth + 1, f"{out} = 99")


KINDS = {
    k: k
    for k in (
        "assign",
        "call",
        "branch",
        "each",
        "loop",
        "dataflow",
        "switch",
        "parallel",
        "ordered",
        "mutate",
        "each_exit",
    )
} | {"try": "try_", "def": "def_", "try_each": "try_each"}


def program(seed: int) -> str:
    g = Gen(seed)
    defined = g.block(0, [], 10)
    g.emit(
        0, f"({', '.join(defined[-2:] or ['0'])})mix(result)" if len(defined) >= 2 else "result = 0"
    )
    return "\n".join(g.lines) + "\n"


@dataclass
class EntryProgram:
    """A generated program, its entry `@def` and sample job inputs."""

    text: str
    entry: str = "main"
    inputs: list[dict] = field(default_factory=list)


def entry_program(seed: int, jobs: int = 4) -> EntryProgram:
    g = EntryGen(seed)
    # Helper `@def`s first, at the top level.
    for _ in range(g.r.randint(0, 2)):
        g.def_(0, [], 3)
    g.emit(0, "@def (a: int, b: int = 3)main(result):")
    defined = g.block(1, ["a", "b"], 12)
    pair = defined[-2:] if len(defined) >= 2 else ["a", "b"]
    g.emit(1, f"({', '.join(pair)})mix(result)")
    inputs = []
    for _ in range(jobs):
        job = {"a": g.r.randint(0, 20)}
        if g.r.random() < 0.5:
            job["b"] = g.r.randint(0, 20)
        inputs.append(job)
    return EntryProgram("\n".join(g.lines) + "\n", "main", inputs)
