"""A namespace entered both by a builtin and by a jump draws behind one labelled merge."""

import json

import pytest

from kohakunode.graph import from_graph, to_graph
from kohakunode.syntax import parse, write

SWITCH = """step = "a"
(step)switch("a"=>`a`, "b"=>`b`)
a:
    y = 2
b:
    x = 1
    ()jump(`a`)
"""

BRANCH = """flag = True
(flag)branch(`yes`, `no`)
yes:
    y = 2
no:
    ()jump(`yes`)
"""

PARALLEL = """()parallel(`p`, `q`)
p:
    y = 2
q:
    ()jump(`p`)
"""

NESTED = """step = "depth"
flag = True
()jump(`decide`)
decide:
    (step)switch("depth"=>`depth`, "breadth"=>`widen`, _=>`done`)
    depth:
        x = 1
        ()jump(`decide`)
    widen:
        (flag)branch(`grown`, `empty`)
        grown:
            ()jump(`depth`)
        empty:
            ()jump(`decide`)
    done:
y = 3
"""


def _edges_into(graph: dict, node: str) -> list[tuple[str, str, str]]:
    return sorted(
        (e["from"]["node"], e["from"]["port"], e["to"]["port"])
        for e in graph["edges"]
        if e["kind"] == "ctrl" and e["to"]["node"] == node
    )


@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize(
    "source, builtin, port, label",
    [
        (SWITCH, "switch", "case_0", "a"),
        (BRANCH, "branch", "true", "yes"),
        (PARALLEL, "parallel", "out_0", "p"),
    ],
)
def test_builtin_and_jump_share_the_labelled_merge(data, source, builtin, port, label):
    graph = to_graph(parse(source), data=data)["graphs"][0]
    nodes = {n["id"]: n for n in graph["nodes"]}
    merges = [n for n in graph["nodes"] if n["kind"] == "merge"]
    assert [m["props"]["label"] for m in merges] == [label]
    merge = merges[0]
    assert merge["ctrl_in"] == ["in_0", "in_1"]
    into = {
        to: (nodes[src]["kind"], src_port) for src, src_port, to in _edges_into(graph, merge["id"])
    }
    assert into["in_0"] == (builtin, port)
    assert set(into) == {"in_0", "in_1"}
    out = [
        e["to"]["node"] for e in graph["edges"] if e["from"] == {"node": merge["id"], "port": "out"}
    ]
    assert len(out) == 1 and nodes[out[0]]["kind"] == "assign"
    assert _edges_into(graph, out[0]) == [(merge["id"], "out", "in")]
    program = parse(source)
    assert from_graph(to_graph(program, data=data), with_meta=False) == program


@pytest.mark.parametrize("data", ["wires", "variables"])
def test_switch_and_jump_from_a_sibling_namespace(data):
    program = parse(NESTED)
    graph = to_graph(program, data=data)["graphs"][0]
    labels = sorted(n["props"]["label"] for n in graph["nodes"] if n["kind"] == "merge")
    assert labels == ["decide", "depth"]
    depth = next(
        n for n in graph["nodes"] if n["kind"] == "merge" and n["props"]["label"] == "depth"
    )
    switch = next(n for n in graph["nodes"] if n["kind"] == "switch")
    branch = next(n for n in graph["nodes"] if n["kind"] == "branch")
    assert _edges_into(graph, depth["id"]) == [
        (branch["id"], "true", "in_1"),
        (switch["id"], "case_0", "in_0"),
    ]
    assert from_graph(to_graph(program, data=data), with_meta=False) == program


@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize("source", [SWITCH, BRANCH, PARALLEL, NESTED])
def test_native_core_draws_and_reads_the_same(data, source):
    native = pytest.importorskip("kohakunode._rs")
    graph = json.loads(native.to_graph(source, [], data))
    assert graph == to_graph(parse(source), data=data)
    assert native.from_graph(json.dumps(graph), False) == write(parse(source))
