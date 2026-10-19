"""Generated programs: every pass keeps behaviour, and graph round trips keep behaviour."""

import pytest

from kohakunode import Interpreter, KirRuntimeError, build_env, compile_source, parse, write
from kohakunode.flow import sort_dataflow
from kohakunode.graph import from_graph, to_graph
from kohakunode.lower import PASSES, run_passes
from progen import LIB, program

SEEDS = range(150)


def outcome(prog, env):
    interp = Interpreter(prog, env, step_budget=20_000)
    try:
        interp.run()
    except KirRuntimeError as exc:
        return ("error", str(exc).split(" (line")[0])
    return ("ok", interp.source_values())


@pytest.mark.parametrize("seed", SEEDS)
def test_every_pass_prefix_keeps_behaviour(seed):
    src = program(seed)
    compiled = compile_source(src, [LIB])
    expected = outcome(compiled.program, build_env(compiled.program, [LIB]))
    names = list(PASSES)
    for k in range(1, len(names) + 1):
        p = run_passes(compiled.program, compiled.env, names[:k])
        assert outcome(p, compiled.env) == expected, (names[:k], src)
    lowered = compiled.lowered
    assert parse(write(lowered)).body == lowered.body
    resorted = parse(write(lowered))
    sort_dataflow(resorted)
    assert write(resorted) == write(lowered), "sorting the optimized program must change nothing"


@pytest.mark.parametrize("seed", SEEDS)
def test_graph_round_trip_keeps_behaviour(seed):
    src = program(seed)
    p = parse(src)
    t1 = from_graph(to_graph(p, build_env(p, [LIB])))
    assert outcome(t1, build_env(t1, [LIB])) == outcome(p, build_env(p, [LIB])), src
    t2 = from_graph(to_graph(t1, build_env(t1, [LIB])))
    assert write(t2) == write(t1), src
