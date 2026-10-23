"""K4 native/reference parse/check/graph/pass/hash/origin parity."""

import argparse
import dataclasses
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
parser = argparse.ArgumentParser()
parser.add_argument("--extension")
args = parser.parse_args()
if args.extension:
    loader = importlib.machinery.ExtensionFileLoader(
        "kohakunode._rs", str(Path(args.extension).resolve())
    )
    spec = importlib.util.spec_from_loader("kohakunode._rs", loader)
    native = importlib.util.module_from_spec(spec)
    loader.exec_module(native)
    sys.modules["kohakunode._rs"] = native
from kohakunode import _rs, compile_source, parse, write  # noqa: E402
from kohakunode.check import check  # noqa: E402
from kohakunode.graph import from_graph, to_graph  # noqa: E402
from kohakunode.sig.env import build_env  # noqa: E402
from kohakunode.sig.files import library_from_json  # noqa: E402
from kohakunode.syntax.ast import walk  # noqa: E402

SOURCES = [
    "xs = [1, 2]\n(xs)collect(item, i, `body`, value -> results)\nbody:\n    (item, i)add(value)\n(results)len(count)\n",
    "([])collect(_, `b`, 7 -> out)\nb:\n    x = 1\n",
    "([1])collect(x, _, `b`, x -> out)\nb:\n    y = x\n",
    "b:\n    value = 1\n([1])collect(x, `b`, value -> out)\n",
    "value = 4\n([1, 2])collect(x, `b`, value -> out)\nb:\n    (x, 1)equal(c)\n    (c)branch(`yes`, `no`)\n    yes:\n        value = 9\n    no:\n        y = x\n",
    "([1])collect(x, `outer`, inner_values -> out)\nouter:\n    ([2])collect(y, `inner`, y -> inner_values)\n    inner:\n        z = y\n",
    "@def (items: list)f(out: list):\n    (items)collect(x, `b`, y -> out)\n    b:\n        (x, 1)add(y)\n([1,2])f(result)\n",
    "@try:\n    ([1])collect(x, `b`, y -> out)\n    b:\n        @try:\n            (x)identity(y)\n        @except err:\n            y = 0\n@except outer:\n    out = []\n",
    "@typehint:\n    (list[int])consume()\n([1])collect(x, `b`, 7 -> out)\nb:\n    y = x\n(out)consume()\n",
    "@def (items: list)f(out: list):\n    (items)collect(x, `b`, y -> out)\n    b:\n        (x, 1)add(y)\n([1])f(a)\n([2])f(b)\n",
    "@typehint:\n    (list[list[str]])consume()\n([1])collect(x, `first`, 7 -> xs)\nfirst:\n    a = x\n([1])collect(y, `second`, xs -> ys)\nsecond:\n    b = y\n(ys)consume()\n",
    "@typehint:\n    (list[list[str]])consume()\nsecond:\n    b = y\nfirst:\n    a = x\n([1])collect(x, `first`, 7 -> xs)\n([1])collect(y, `second`, xs -> ys)\n(ys)consume()\n",
    "xs = []\n([1])collect(x, `a`, ys -> xs)\na:\n    y = 1\n([1])collect(z, `b`, xs -> ys)\nb:\n    w = 2\n",
    "([1])collect(x, `b`, missing -> out)\nb:\n    y = x\n",
    "([1])collect(out, `b`, out -> out)\nb:\n    y = 1\n",
    "([1])collect(x, `b`, x -> out)\nb:\n    out = x\n",
    "([1])collect(x, `b`, x -> out)\nb:\n    ()jump(`outside`)\noutside:\n    y = 1\n",
    "([1])collect(x, `b`, x -> out)\nb:\n    y = x\n()jump(`b`)\n",
]


def origins(items):
    return [
        x
        for s in items
        for x in [s.get("origin"), *origins(s.get("body", [])), *origins(s.get("handler", []))]
    ]


count = 0
for source in SOURCES:
    program = parse(source)
    assert _rs.format(source) == write(program)
    env = build_env(program)
    diags = check(program, env)
    expected = [
        {"code": d.code, "message": d.message, "line": d.line, "severity": d.severity}
        for d in diags
    ]
    assert json.loads(_rs.check(source)) == expected, (
        source,
        "check",
        json.loads(_rs.check(source)),
        expected,
    )
    for style in ["wires", "variables"]:
        try:
            graph = to_graph(program, env, data=style)
        except Exception:
            continue
        got = json.loads(_rs.to_graph(source, data=style))
        assert got == graph, (source, style, "graph", got, graph)
        for meta in [False, True]:
            assert _rs.from_graph(json.dumps(graph), meta) == write(
                from_graph(graph, with_meta=meta)
            ), (source, style, "from graph")
    if not any(d.severity == "error" for d in diags):
        for passes in [
            [],
            ["expand_collect"],
            ["order_dataflow", "expand_collect", "inline"],
            ["order_dataflow", "inline", "expand_collect"],
            None,
        ]:
            expected = compile_source(source, passes=passes)
            got = json.loads(_rs.compile_modules(source, "{}", passes=passes))
            assert got["text"] == write(expected.program)
            assert got["lowered_text"] == write(expected.lowered), (
                source,
                passes,
                "lower",
                got["lowered_text"],
                write(expected.lowered),
            )
            assert got["semantic"] == expected.semantic_hash, (source, passes, "semantic")
            assert got["full"] == expected.full_hash, (source, passes, "full")
            expected_origins = json.loads(
                json.dumps(
                    [
                        dataclasses.asdict(s.origin) if s.origin else None
                        for s in walk(expected.lowered.body)
                    ]
                )
            )
            assert origins(got["lowered"]["body"]) == expected_origins, (source, passes, "origins")
    count += 1
# Source linking rewrites definition calls without losing deferred result identity.
modules = {
    "lib.kir": "@export gather\n@def (items: list)gather(out: list):\n    (items)collect(x, `b`, y -> out)\n    b:\n        (x, 1)add(y)\n"
}
source = '@import "lib.kir" as lib\n([1,2])lib.gather(result)\n'
for passes in [[], ["order_dataflow", "expand_collect", "inline"], None]:
    expected = compile_source(source, modules=modules, source_name="main.kir", passes=passes)
    got = json.loads(_rs.compile_modules(source, json.dumps(modules), "main.kir", passes=passes))
    assert got["lowered_text"] == write(expected.lowered)
    assert got["semantic"] == expected.semantic_hash
    assert got["dependencies"] == expected.dependencies
    count += 1

contract = {
    "kirsig": 1,
    "library": "host",
    "nodes": [
        {
            "name": "mutate",
            "inputs": [{"name": "value"}],
            "outputs": [],
            "flags": {"mutates": ["value"], "ordered": False},
        }
    ],
}
for source in [
    "([1])collect(x, `b`, x -> out)\nb:\n    y = x\n(out)mutate()\n",
    "@def (x)unused():\n    (x)mutate()\n([1])collect(x, `b`, x -> out)\nb:\n    y = x\n",
]:
    env = build_env(parse(source), [library_from_json(contract)])
    expected = [
        {"code": d.code, "message": d.message, "line": d.line, "severity": d.severity}
        for d in check(parse(source), env)
    ]
    assert json.loads(_rs.check(source, [json.dumps(contract)])) == expected
    assert any(d["code"] == "E072" for d in expected)
    count += 1

# A graph cannot silently turn a deferred sample into an eager ordinary input.
source = SOURCES[0]
graph = to_graph(parse(source), build_env(parse(source)))
node = next(n for n in graph["graphs"][0]["nodes"] if n["kind"] == "collect")
next(p for p in node["inputs"] if p["port"] == "value").pop("deferred")
for fn in [lambda: from_graph(graph), lambda: _rs.from_graph(json.dumps(graph), False)]:
    try:
        fn()
    except Exception as exc:
        assert str(exc) == "collect requires a value input deferred to body_end"
    else:
        raise AssertionError("accepted eager graph collect sample")
count += 1
print(f"Collect parity: {count} programs passed")
