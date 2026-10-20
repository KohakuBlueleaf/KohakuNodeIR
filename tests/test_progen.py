"""Generated programs end: every one finishes under the reference within a call bound."""

from functools import partial

import pytest

from kohakunode import Interpreter, KirRuntimeError, build_env, compile_source, parse
from kohakunode.testing import EFFECTS
from progen import LIB, entry_program, program

SEEDS = range(400)
BOUND = 200_000


def ends(run) -> bool:
    """False only when the run hits the call bound; other runtime errors are endings."""
    try:
        run()
    except KirRuntimeError as exc:
        return f"more than {BOUND} node calls" not in str(exc)
    return True


@pytest.mark.parametrize("seed", SEEDS)
def test_programs_end(seed):
    src = program(seed)
    p = parse(src)
    interp = Interpreter(p, build_env(p, [LIB]), step_budget=BOUND)
    assert ends(interp.run), src


@pytest.mark.parametrize("seed", SEEDS)
def test_entry_programs_end(seed):
    ep = entry_program(seed)
    compiled = compile_source(ep.text, [LIB])
    for inputs in ep.inputs:
        interp = Interpreter(compiled.program, compiled.env, step_budget=BOUND)
        assert ends(partial(interp.call, ep.entry, inputs)), (inputs, ep.text)
    EFFECTS.clear()
