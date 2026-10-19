"""Text <-> graph view: canonical text is a fixed point, and conversion keeps behaviour."""

import contextlib
import io
import json
from pathlib import Path

import pytest

from kohakunode import Interpreter, build_env, parse, write
from kohakunode.graph import from_graph, to_graph
from test_pipeline import EACH, LIB
from test_v1_parity import EXPECTED, library_for

CORPUS = Path(__file__).parent / "corpus" / "v1"


def ok_files():
    for path in sorted(CORPUS.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "ok" and record["file"] not in EXPECTED:
            yield pytest.param(path.with_suffix(".kir"), id=record["file"])


def run_output(program, lib):
    buf = io.StringIO()
    interp = Interpreter(program, build_env(program, [lib]), step_budget=100_000)
    with contextlib.redirect_stdout(buf):
        values = interp.run()
    return buf.getvalue(), values


V2 = {
    "each": EACH,
    "try": 'image = "img"\n@try:\n    (image, 13)crop(c)\n    (c)entity(node)\n@except err:\n    node = None\n(node)identity(out)\n',
    "def": '@def (image, box: int = 2)expand(node):\n    (image, box)crop(c)\n    (c)entity(node)\n\n("img", 1)expand(a)\n("img")expand(b)\n',
    "switch": "x = 2\n(x)switch(1=>`a`, 2=>`b`, _=>`c`)\na:\n    y = 1\nb:\n    y = 2\nc:\n    y = 3\n(y)identity(z)\n",
    "parallel": "()parallel(`a`, `b`)\na:\n    p = 1\nb:\n    q = 2\n(p, q)add(r)\n",
    "dataflow": "@dataflow:\n    (b)identity(c)\n    a = 1\n    (a)identity(b)\n(c)identity(d)\n",
}


STYLES = ("wires", "variables")


@pytest.mark.parametrize("data", STYLES)
@pytest.mark.parametrize("name", sorted(V2))
def test_graph_round_trip_v2(name, data):
    program = parse(V2[name])
    g1 = to_graph(program, build_env(program, [LIB]), data)
    t1 = from_graph(json.loads(json.dumps(g1)))
    t2 = from_graph(to_graph(t1, build_env(t1, [LIB]), data))
    assert write(t2) == write(t1)
    assert run_output(t1, LIB)[1] == run_output(program, LIB)[1]


@pytest.mark.parametrize("data", STYLES)
@pytest.mark.parametrize("path", list(ok_files()))
def test_graph_round_trip(path, data):
    program = parse(path.read_text(encoding="utf-8"))
    lib = library_for(program)
    env = build_env(program, [lib])
    g1 = to_graph(program, env, data)
    json.dumps(g1)
    t1 = from_graph(g1)
    g2 = to_graph(t1, build_env(t1, [lib]), data)
    t2 = from_graph(g2)
    assert write(t2) == write(t1)
    assert g2 == to_graph(t2, build_env(t2, [lib]), data)
    assert run_output(t1, lib) == run_output(program, lib)


def test_variables_style_shape():
    program = parse(V2["each"])
    g = to_graph(program, build_env(program, [LIB]), "variables")["graphs"][0]
    nodes = {n["id"]: n for n in g["nodes"]}
    for n in nodes.values():
        if n["kind"] in ("get", "set"):
            assert "ctrl_in" not in n and "ctrl_out" not in n
    for e in g["edges"]:
        if e["kind"] == "data":
            # Every data wire starts at a variable read or ends at a variable write.
            assert (
                nodes[e["from"]["node"]]["kind"] == "get" or nodes[e["to"]["node"]]["kind"] == "set"
            )
    image = next(n for n in nodes.values() if n["kind"] == "assign")
    assert image["inputs"] == [{"port": "value", "value": "img"}]


def test_editor_style_graph_reads_back():
    """Literal and variable nodes the way an editor draws them: value → add → set out."""
    graph = {
        "kirgraph": 2,
        "uses": [],
        "graphs": [
            {
                "name": "main",
                "nodes": [
                    {
                        "id": "one",
                        "kind": "value",
                        "props": {"value": 1},
                        "outputs": [{"port": "value"}],
                    },
                    {
                        "id": "add",
                        "kind": "call",
                        "name": "add",
                        "inputs": [{"port": "a"}, {"port": "b", "value": 2}],
                        "outputs": [{"port": "sum"}],
                        "ctrl_in": [],
                        "ctrl_out": [],
                    },
                    {
                        "id": "out",
                        "kind": "set",
                        "props": {"name": "out"},
                        "inputs": [{"port": "value"}],
                    },
                    {
                        "id": "x",
                        "kind": "get",
                        "props": {"name": "out"},
                        "outputs": [{"port": "value"}],
                    },
                    {
                        "id": "eq",
                        "kind": "assign",
                        "inputs": [{"port": "value"}],
                        "outputs": [{"port": "value"}],
                        "ctrl_in": [],
                        "ctrl_out": [],
                    },
                    {
                        "id": "y",
                        "kind": "set",
                        "props": {"name": "y"},
                        "inputs": [{"port": "value"}],
                    },
                ],
                "edges": [
                    {
                        "kind": "data",
                        "from": {"node": "one", "port": "value"},
                        "to": {"node": "add", "port": "a"},
                    },
                    {
                        "kind": "data",
                        "from": {"node": "add", "port": "sum"},
                        "to": {"node": "out", "port": "value"},
                    },
                    {
                        "kind": "data",
                        "from": {"node": "x", "port": "value"},
                        "to": {"node": "eq", "port": "value"},
                    },
                    {
                        "kind": "data",
                        "from": {"node": "eq", "port": "value"},
                        "to": {"node": "y", "port": "value"},
                    },
                ],
            }
        ],
    }
    assert (
        write(from_graph(graph, with_meta=False)) == "@dataflow:\n    (1, 2)add(out)\n    y = out\n"
    )
