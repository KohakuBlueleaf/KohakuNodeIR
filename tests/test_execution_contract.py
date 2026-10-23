"""Fixed outcomes, not elapsed clocks, define these reference contract checks."""

import copy
from collections import deque

import pytest

from kohakunode import Interpreter, build_env, compile_program, full_hash, parse, semantic_hash
from kohakunode.sig import Library, Port, Signature
from kohakunode.syntax.ast import walk

SOURCE = """@use "recorded" as r
@meta node_id="before"
@hint lane="preferred" priority=100
()r.before(before)
@try:
    @hint timeout_s=0 retry=99 cancel=True step_budget=0
    ()r.fetch(value)
    @hint lane="branch"
    (value)branch(`accepted`, `rejected`)
    accepted:
        @hint max_wait_ms=10
        (value)r.accept(result)
    rejected:
        @hint retry=3
        (value)r.reject(result)
@except err:
    @hint lane="recovery"
    (err)r.recover(result)
@hint work_budget=0
(result)r.finish(final)
"""


def _unreachable_implementation(**inputs):
    raise AssertionError("a fixed-outcome replay must not call the external implementation")


def _library():
    library = Library("recorded")
    for name, inputs in (
        ("before", ()),
        ("fetch", ()),
        ("accept", ("value",)),
        ("reject", ("value",)),
        ("recover", ("error",)),
        ("finish", ("result",)),
    ):
        library.add_signature(
            Signature(name, tuple(Port(name) for name in inputs), (Port("output"),)),
            _unreachable_implementation,
        )
    return library


def _replay(program, outcomes, lowered):
    library = _library()
    if lowered:
        compiled = compile_program(program, [library])
        program, env = compiled.lowered, compiled.env
    else:
        env = build_env(program, [library])
    pending = deque(outcomes)
    consumed = []

    def hook(name, inputs, call):
        expected_name, expected_inputs, outcome = pending.popleft()
        assert name == expected_name
        assert inputs == expected_inputs
        consumed.append((name, copy.deepcopy(inputs)))
        if isinstance(outcome, Exception):
            raise outcome
        return copy.deepcopy(outcome)

    interpreter = Interpreter(program, env, hook=hook)
    interpreter.run()
    assert not pending
    return interpreter.source_values(), consumed


def _without_annotations(program):
    result = copy.deepcopy(program)
    for statement in walk(result.body):
        statement.hint.clear()
        statement.meta.clear()
    return result


@pytest.mark.parametrize("lowered", [False, True])
@pytest.mark.parametrize("condition", [False, True])
def test_advisory_deletion_preserves_success_trace_control_outputs_and_semantic_hash(
    lowered, condition
):
    program = parse(SOURCE)
    stripped = _without_annotations(program)
    branch = "accept" if condition else "reject"
    outcomes = [
        ("r.before", {}, "retained"),
        ("r.fetch", {}, condition),
        (f"r.{branch}", {"value": condition}, branch),
        ("r.finish", {"result": branch}, "finished"),
    ]
    annotated_result = _replay(program, outcomes, lowered)
    stripped_result = _replay(stripped, outcomes, lowered)
    assert annotated_result == stripped_result
    values, calls = annotated_result
    assert values == {
        "before": "retained",
        "value": condition,
        "result": branch,
        "final": "finished",
    }
    assert [name for name, _ in calls] == ["r.before", "r.fetch", f"r.{branch}", "r.finish"]
    assert semantic_hash(program) == semantic_hash(stripped)
    assert full_hash(program) != full_hash(stripped)
    annotated = compile_program(program, [_library()])
    unannotated = compile_program(stripped, [_library()])
    assert annotated.semantic_hash == unannotated.semantic_hash


@pytest.mark.parametrize("lowered", [False, True])
@pytest.mark.parametrize("error_type", [TimeoutError, ValueError])
def test_recorded_error_selects_handler_without_reference_clock_or_retry(lowered, error_type):
    program = parse(SOURCE)
    stripped = _without_annotations(program)
    error = {"kind": error_type.__name__, "node": "r.fetch", "message": "recorded failure"}
    outcomes = [
        ("r.before", {}, "retained"),
        ("r.fetch", {}, error_type("recorded failure")),
        ("r.recover", {"error": error}, "recovered"),
        ("r.finish", {"result": "recovered"}, "finished"),
    ]
    annotated_result = _replay(program, outcomes, lowered)
    assert annotated_result == _replay(stripped, outcomes, lowered)
    values, calls = annotated_result
    assert values == {
        "before": "retained",
        "err": error,
        "result": "recovered",
        "final": "finished",
    }
    assert [name for name, _ in calls] == ["r.before", "r.fetch", "r.recover", "r.finish"]
    assert sum(name == "r.fetch" for name, _ in calls) == 1
    assert "value" not in values
    assert semantic_hash(program) == semantic_hash(stripped)


def test_program_hash_is_not_a_certificate_of_host_implementation_results():
    program = parse('@use "external" as ext\n(7)ext.transform(result)\n')
    signature = Signature("transform", (Port("value"),), (Port("result"),))

    def first(value):
        return value + 1

    def second(value):
        return value + 2

    hashes, outputs = [], []
    for implementation in (first, second):
        library = Library("external")
        library.add_signature(signature, implementation)
        compiled = compile_program(program, [library])
        interpreter = Interpreter(compiled.lowered, compiled.env)
        interpreter.run()
        hashes.append((compiled.semantic_hash, compiled.full_hash))
        outputs.append(interpreter.source_values())
    assert hashes[0] == hashes[1]
    assert outputs == [{"result": 8}, {"result": 9}]
