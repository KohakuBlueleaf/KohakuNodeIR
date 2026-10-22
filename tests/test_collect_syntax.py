"""Collect syntax, delayed CFG sampling, and explicit deferred graph inputs."""

import json

import pytest

from kohakunode.errors import KirGraphError, KirSyntaxError
from kohakunode.flow.cfg import UNDEF, build_cfg, defs_of, reaching
from kohakunode.flow.order import is_simple, sort_dataflow
from kohakunode.graph import from_graph, to_graph
from kohakunode.syntax import parse, write
from kohakunode.syntax.ast import (
    BUILTINS,
    Assign,
    Call,
    Collect,
    Each,
    Literal,
    Name,
    Origin,
    deferred_reads,
    labels_entered,
    reads,
    walk,
    writes,
)


@pytest.mark.parametrize(
    "source, expected",
    [
        (
            "(xs)collect(item, `body`, value -> results)",
            Collect(Name("xs"), "item", None, "body", Name("value"), "results"),
        ),
        (
            "(xs)collect(item, index, `body`, value -> results)",
            Collect(Name("xs"), "item", "index", "body", Name("value"), "results", True),
        ),
        (
            "([])collect(_, _, `body`, None -> results)",
            Collect(Literal([]), None, None, "body", Literal(None), "results", True),
        ),
        (
            "([1, 2])collect(item, `body`, [1, 2] -> results)",
            Collect(Literal([1, 2]), "item", None, "body", Literal([1, 2]), "results"),
        ),
        (
            "(xs)collect(_, `body`, -1 -> results)",
            Collect(Name("xs"), None, None, "body", Literal(-1), "results"),
        ),
    ],
)
def test_collect_parse_write_and_ast(source, expected):
    program = parse(source + "\nbody:\n")
    assert type(program.body[0]) is Collect
    assert program.body[0] == expected
    assert program.body[0].line == 1
    assert write(program) == source + "\nbody:\n"
    assert parse(write(program)) == program
    assert "collect" in BUILTINS
    assert not isinstance(expected, Each)
    assert not is_simple(expected)


@pytest.mark.parametrize(
    "source",
    [
        "()collect(item, `body`, value -> results)",
        "(xs)collect(results)",
        "(xs, ys)collect(item, `body`, value -> results)",
        "(items=xs)collect(item, `body`, value -> results)",
        "(xs)collect(`body`, value -> results)",
        "(xs)collect(a, b, c, `body`, value -> results)",
        "(xs)collect(item, body, value -> results)",
        "(xs)collect(item, `body`, value)",
        "(xs)collect(item, `body`, value -> _)",
        "(xs)collect(item, `body`, _ -> results)",
        "(xs)collect(item, `body`, value -> results, other)",
        "(xs)collect(item, value -> results, `body`)",
        "(xs)collect(item, `body`, value -> results, value -> more)",
        "(xs)each(item, `body`, value -> results)",
        "(xs)host.collect(item, `body`, value -> results)",
        "(xs)host(value -> results)",
        "(xs)collect(item, `body`, value => `results`)",
    ],
)
def test_collect_shape_errors_do_not_change_existing_calls(source):
    with pytest.raises(KirSyntaxError):
        parse(source + "\n")


@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize("with_meta", [False, True])
def test_qualified_host_collect_remains_an_ordinary_call(data, with_meta):
    source = '@use "host" as h\n\n([1, 2], limit=2)h.collect(results, _)\n'
    program = parse(source)
    call = program.body[0]
    assert type(call) is Call and call.name == "h.collect"
    assert call.outs == ["results", None]
    assert call.args[1].key == "limit"
    assert write(program) == source
    graph = to_graph(program, data=data)
    assert not any(n["kind"] == "collect" for g in graph["graphs"] for n in g["nodes"])
    node = next(n for n in graph["graphs"][0]["nodes"] if n["kind"] == "call")
    assert node["name"] == "h.collect"
    assert all("deferred" not in port for port in node["inputs"])
    restored = from_graph(graph, with_meta=with_meta)
    assert type(restored.body[0]) is Call and restored.body[0].name == "h.collect"
    assert write(from_graph(to_graph(restored, data=data), with_meta=with_meta)) == write(restored)
    if not with_meta:
        assert restored == program


def test_inventory_distinguishes_entry_and_deferred_reads():
    collect = parse("(xs)collect(item, index, `body`, value -> results)\n").body[0]
    assert reads(collect) == ["xs"]
    assert deferred_reads(collect) == ["value"]
    assert writes(collect) == ["item", "index", "results"]
    assert labels_entered(collect) == ["body"]
    literal = Collect(Literal([]), None, None, "body", Literal(None), "results")
    assert reads(literal) == deferred_reads(literal) == []
    assert writes(literal) == ["results"]


SIMPLE = "xs = [1, 2]\n(xs)collect(item, index, `body`, value -> results)\nbody:\n    value = item\n(results)consume(out)\n"


def test_cfg_samples_after_body_and_publishes_only_on_completion():
    program = parse(SIMPLE)
    collect, namespace, consumer = program.body[1:]
    assignment = namespace.body[0]
    cfg = build_cfg(program.body)
    controller = cfg.node_of[id(collect)]
    bind = cfg.binds[id(collect)]
    sample = cfg.samples[id(collect)]
    done = cfg.completions[id(collect)]
    assert len({controller, bind, sample, done}) == 4
    assert cfg.nodes[controller].reads == ("xs",) and cfg.nodes[controller].writes == ()
    assert cfg.nodes[bind].writes == ("item", "index")
    assert cfg.nodes[sample].kind == "collect_sample"
    assert cfg.nodes[sample].stmt is collect
    assert cfg.nodes[sample].reads == ("value",) and cfg.nodes[sample].writes == ()
    assert cfg.nodes[done].kind == "collect_done"
    assert cfg.nodes[done].stmt is collect
    assert cfg.nodes[done].writes == ("results",)
    assert cfg.succ[sample] == [(controller, "flow")]
    assert cfg.succ[done] == [(cfg.node_of[id(consumer)], "flow")]
    assert (sample, "flow") in cfg.succ[cfg.node_of[id(assignment)]]
    assert cfg.owners[id(namespace)] == [collect]
    inn = reaching(cfg, ("xs", "value", "results"))
    assert defs_of(inn[sample], "value") == {cfg.node_of[id(assignment)]}
    assert defs_of(inn[cfg.node_of[id(consumer)]], "results") == {done}
    assert defs_of(inn[bind], "results") == {UNDEF}


def test_cfg_missing_deferred_value_is_visible_and_does_not_read_at_entry():
    program = parse("([])collect(item, `body`, missing -> results)\nbody:\n")
    collect = program.body[0]
    cfg = build_cfg(program.body)
    inn = reaching(cfg, ("missing", "results"))
    assert cfg.nodes[cfg.node_of[id(collect)]].reads == ()
    assert cfg.nodes[cfg.samples[id(collect)]].reads == ("missing",)
    assert defs_of(inn[cfg.samples[id(collect)]], "missing") == {UNDEF}
    assert defs_of(inn[cfg.exit], "results") == {cfg.completions[id(collect)]}


def test_cfg_loop_carried_reads_remain_valid_at_normal_body_end():
    program = parse(
        "state = 0\n([1, 2])collect(item, `body`, state -> results)\nbody:\n    (state, item)add(state)\n"
    )
    collect = program.body[1]
    update = program.body[2].body[0]
    cfg = build_cfg(program.body)
    inn = reaching(cfg, ("state", "results"))
    assert defs_of(inn[cfg.samples[id(collect)]], "state") == {cfg.node_of[id(update)]}
    assert defs_of(inn[cfg.node_of[id(update)]], "state") == {
        cfg.node_of[id(program.body[0])],
        cfg.node_of[id(update)],
    }


GRAPH_CASES = [
    SIMPLE,
    "([1, 2])collect(item, `body`, item -> results)\nbody:\n",
    "([])collect(_, _, `body`, None -> results)\nbody:\n",
    "([1])collect(item, `body`, [1, 2] -> results)\nbody:\n",
    "([True, False])collect(item, `body`, value -> results)\nbody:\n    (item)branch(`yes`, `no`)\n    yes:\n        value = 1\n    no:\n        value = 2\n",
    "([1])collect(item, `body`, inner -> outer)\nbody:\n    ([2])collect(other, `nested`, other -> inner)\n    nested:\n",
    "@def (xs)gather(results):\n    (xs)collect(item, `body`, item -> results)\n    body:\n",
    "state = 0\n([1, 2])collect(item, `body`, state -> results)\nbody:\n    (state, item)add(state)\n",
    "([1])collect(item, `body`, value -> results)\nbody:\n    @try:\n        (item)maybe(value)\n    @except error:\n        value = None\n",
]


@pytest.mark.parametrize("source", GRAPH_CASES)
@pytest.mark.parametrize("data", ["wires", "variables"])
@pytest.mark.parametrize("with_meta", [False, True])
def test_collect_graph_round_trip_origins_and_text_fixed_point(source, data, with_meta):
    program = parse(source)
    for index, statement in enumerate(walk(program.body)):
        statement.origin = Origin("collect.kir", f"stmt_{index}", statement.line)
    graph = json.loads(json.dumps(to_graph(program, data=data)))
    restored = from_graph(graph, with_meta=with_meta)
    assert {s.origin for s in walk(restored.body) if s.origin} == {
        s.origin for s in walk(program.body)
    }
    assert write(from_graph(to_graph(restored, data=data), with_meta=with_meta)) == write(restored)
    erased = parse(write(restored))
    assert write(from_graph(to_graph(erased, data=data), with_meta=with_meta)) == write(restored)
    if not with_meta:
        assert restored == program


@pytest.mark.parametrize("data", ["wires", "variables"])
def test_graph_defers_namespace_declared_before_collect(data):
    program = parse(
        "body:\n    value = item\n([1])collect(item, `body`, value -> results)\n(results)consume(out)\n"
    )
    for index, statement in enumerate(walk(program.body)):
        statement.origin = Origin("forward.kir", str(index))
    graph = to_graph(program, data=data)
    restored = from_graph(graph, with_meta=False)
    assert isinstance(restored.body[0], Collect)
    assert len(restored.body) == 3
    assert restored.body[1].body == program.body[0].body
    assert sum(n["kind"] == "assign" for n in graph["graphs"][0]["nodes"]) == 1
    assert {s.origin for s in walk(restored.body)} == {s.origin for s in walk(program.body)}
    assert write(from_graph(to_graph(restored, data=data), with_meta=False)) == write(restored)


def test_cfg_exception_does_not_publish_partial_collect_target():
    program = parse(
        "results = [0]\n@try:\n    ([1])collect(item, `body`, value -> results)\n    body:\n        (item)may_fail(value)\n@except error:\n    (results)consume(failed)\n"
    )
    attempt = program.body[1]
    collect = attempt.body[0]
    handler = attempt.handler[0]
    cfg = build_cfg(program.body)
    inn = reaching(cfg, ("results", "value"))
    assert defs_of(inn[cfg.node_of[id(handler)]], "results") == {cfg.node_of[id(program.body[0])]}
    assert cfg.nodes[cfg.completions[id(collect)]].writes == ("results",)


def test_graph_value_wire_comes_from_body_end_not_entry():
    program = parse(
        "value = 0\n([1])collect(item, `body`, value -> results)\nbody:\n    value = item\n(results)consume(out)\n"
    )
    graph = to_graph(program)["graphs"][0]
    nodes = {n["id"]: n for n in graph["nodes"]}
    collect = next(n for n in nodes.values() if n["kind"] == "collect")
    assert collect["inputs"][1] == {"port": "value", "deferred": "body_end"}
    assert collect["ctrl_in"] == ["in", "next"]
    assert collect["ctrl_out"] == ["body", "done"]
    value_edge = next(
        e
        for e in graph["edges"]
        if e["kind"] == "data" and e["to"] == {"node": collect["id"], "port": "value"}
    )
    writer = nodes[value_edge["from"]["node"]]
    assert writer["kind"] == "assign" and "value" not in writer["inputs"][0]
    consumer = next(n for n in nodes.values() if n.get("name") == "consume")
    assert any(
        e["from"] == {"node": collect["id"], "port": "results"}
        and e["to"] == {"node": consumer["id"], "port": "in0"}
        for e in graph["edges"]
    )


@pytest.mark.parametrize("marker", [None, "entry", True])
def test_graph_reader_requires_explicit_deferred_value_input(marker):
    graph = to_graph(parse(SIMPLE))
    collect = next(n for n in graph["graphs"][0]["nodes"] if n["kind"] == "collect")
    collect["inputs"][1]["deferred"] = marker
    with pytest.raises(KirGraphError, match="deferred"):
        from_graph(graph)


def test_dataflow_ordering_inside_collect_body_preserves_origin():
    program = parse(
        "([1])collect(item, `body`, value -> results)\nbody:\n    @dataflow:\n        (intermediate)identity(value)\n        intermediate = item\n"
    )
    collect = program.body[0]
    collect.origin = Origin("collect.kir", "collect")
    sort_dataflow(program)
    assert program.body[0] is collect and collect.origin == Origin("collect.kir", "collect")
    assert isinstance(program.body[1].body[0].body[0], Assign)
