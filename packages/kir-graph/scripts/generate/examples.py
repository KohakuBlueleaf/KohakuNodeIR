"""The example graphs the dev gallery and the layout checks read: python scripts/generate/examples.py

Writes ``dev/examples/<id>.json`` (the program text and its graph in both data
styles; a program with ``@def``s also gets ``whole``, main with every ``@def``
inlined) and ``dev/examples/index.json``. Sources:

- the KIR examples (basics, tour, gbc) with their node libraries;
- the golden corpus (``tests/corpus/golden/cases``) with its signature files;
- generated programs: every construct nested deep, and a large program
  (``--large`` statements, 2000 by default) for layout cost.
"""

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent.parent
REPO = PACKAGE.parent.parent
OUT = PACKAGE / "dev" / "examples"
EXAMPLES = REPO / "examples"
GOLDEN = REPO / "tests" / "corpus" / "golden" / "cases"
sys.path.insert(0, str(EXAMPLES))

from basics.nodes import LIB as BASICS  # noqa: E402
from gbc.nodes import LIB as GBC  # noqa: E402
from tour.nodes import LIB as TOUR  # noqa: E402

from kohakunode import parse  # noqa: E402
from kohakunode.graph import to_graph  # noqa: E402
from kohakunode.graph.to_graph import DATA_STYLES  # noqa: E402
from kohakunode.lower.passes import run_passes  # noqa: E402
from kohakunode.sig import library_from_json  # noqa: E402
from kohakunode.sig.env import build_env  # noqa: E402
from kohakunode.syntax.ast import Def  # noqa: E402

SUITES = {"basics": BASICS, "tour": TOUR, "gbc": GBC}
# The graph holding a program with every `@def` inlined into main
WHOLE = "whole"


def graphs(src: str, libs: list) -> dict:
    """The program's graphs in every data style; with `@def`s, also `whole`: main with every `@def` inlined."""
    program = parse(src)
    env = build_env(program, libs) if libs else None
    out = {style: to_graph(program, env, style) for style in DATA_STYLES}
    if env is None or not any(isinstance(s, Def) for s in program.body):
        return out
    flat = run_passes(program, env, ["order_dataflow", "inline"])
    for style in DATA_STYLES:
        main = next(g for g in to_graph(flat, env, style)["graphs"] if g["name"] == "main")
        out[style]["graphs"].append({**main, "name": WHOLE})
    return out


def nested() -> str:
    """Every construct, each inside the one before."""
    return "\n".join(
        [
            "@def (xs: list, limit: int = 3)score_all(total, report):",
            "    total = 0",
            "    report = []",
            "    (xs)collect(x, i, `per_item`, line -> report)",
            "    per_item:",
            "        @try:",
            "            (x)measure(size, ok)",
            "            (ok)branch(`fine`, `broken`)",
            "            fine:",
            "                (size)switch(0=>`empty`, 1=>`one`, _=>`many`)",
            "                empty:",
            '                    line = "empty"',
            "                one:",
            "                    @dataflow:",
            "                        (size, 2)mul(double)",
            "                        (double, total)add(total)",
            '                    line = "one"',
            "                many:",
            "                    ()parallel(`left`, `right`)",
            "                    left:",
            "                        (x)left_half(a)",
            "                    right:",
            "                        (x)right_half(b)",
            "                    (a, b)combine(line)",
            "            broken:",
            '                line = "broken"',
            "        @except err:",
            "            (err)describe(line)",
            "",
            "items = [1, 2, 3]",
            "n = 0",
            "()jump(`again`)",
            "again:",
            "    (items, 3)score_all(total, report)",
            "    (n, 1)add(n)",
            "    (n, 3)lt(more)",
            "    (more)branch(`repeat`, `stop`)",
            "    repeat:",
            "        ()jump(`again`)",
            "    stop:",
            "(total, report)publish()",
            "",
        ]
    )


def large(statements: int, seed: int = 7) -> str:
    """A long program of calls with branches, loops, tries and dataflow blocks, deterministic."""
    rng = random.Random(seed)
    lines: list[str] = []
    names = ["seed"]
    count = 0
    label = 0

    def fresh() -> str:
        nonlocal label
        label += 1
        return f"l{label}"

    # Outputs reuse a pool of names, as programs reuse variables
    def call(indent: str) -> None:
        nonlocal count
        count += 1
        args = ", ".join(rng.sample(names, min(len(names), rng.randint(1, 3))))
        out = f"v{count % 32}"
        lines.append(f"{indent}({args})op{rng.randint(0, 40)}({out})")
        if out not in names:
            names.append(out)

    def block(indent: str, depth: int, budget: int) -> None:
        nonlocal count
        call(indent)
        budget -= 1
        while budget > 0 and count < statements:
            roll = rng.random()
            if depth < 4 and roll < 0.06:
                a, b = fresh(), fresh()
                lines.append(f"{indent}({rng.choice(names)})branch(`{a}`, `{b}`)")
                for lab in (a, b):
                    lines.append(f"{indent}{lab}:")
                    block(indent + "    ", depth + 1, rng.randint(2, 6))
                budget -= 4
            elif depth < 4 and roll < 0.10:
                body = fresh()
                lines.append(f"{indent}({rng.choice(names)})each(item, `{body}`)")
                lines.append(f"{indent}{body}:")
                if "item" not in names:
                    names.append("item")
                block(indent + "    ", depth + 1, rng.randint(2, 8))
                budget -= 4
            elif depth < 4 and roll < 0.12:
                lines.append(f"{indent}@try:")
                block(indent + "    ", depth + 1, rng.randint(2, 5))
                lines.append(f"{indent}@except err:")
                block(indent + "    ", depth + 1, rng.randint(1, 3))
                budget -= 4
            elif depth < 4 and roll < 0.14:
                lines.append(f"{indent}@dataflow:")
                for _ in range(rng.randint(2, 4)):
                    call(indent + "    ")
                budget -= 3
            else:
                call(indent)
                budget -= 1

    block("", 0, statements)
    while count < statements:
        call("")
    return "seed = 0\n" + "\n".join(lines) + "\n"


def entries(statements: int):
    for folder, lib in SUITES.items():
        for path in sorted((EXAMPLES / folder).glob("*.kir")):
            yield f"{folder}__{path.stem}", f"{folder}/{path.name}", "examples", path.read_text(
                "utf-8"
            ), [lib]
    for d in sorted(GOLDEN.iterdir()):
        lib = library_from_json(json.loads((d / "sig.kirsig.json").read_text("utf-8")))
        yield f"golden__{d.name}", d.name, "golden corpus", (d / "input.kir").read_text("utf-8"), [
            lib
        ]
    yield "generated__nested", "every construct, nested", "generated", nested(), []
    yield "generated__large", f"{statements} statements", "generated", large(statements), []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--large", type=int, default=2000, help="statements of the large program")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for ident, title, group, src, libs in entries(args.large):
        try:
            g = graphs(src, libs)
        except Exception as exc:  # a corpus program the graph view cannot draw is listed as such
            index.append(
                {
                    "id": ident,
                    "title": title,
                    "group": group,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        doc = {"id": ident, "title": title, "group": group, "source": src, "graphs": g}
        (OUT / f"{ident}.json").write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
        nodes = sum(len(x["nodes"]) for x in g["wires"]["graphs"])
        index.append({"id": ident, "title": title, "group": group, "nodes": nodes})
    (OUT / "index.json").write_text(json.dumps(index, indent=1), "utf-8")
    print(f"wrote {len(index)} examples to {OUT}")


if __name__ == "__main__":
    main()
