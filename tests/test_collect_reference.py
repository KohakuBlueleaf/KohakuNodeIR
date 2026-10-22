"""Collect's direct private builder and explicit append baseline have one meaning."""

import gc
import weakref
from typing import Any

import pytest

from kohakunode import (
    Interpreter,
    KirRuntimeError,
    NodeFailure,
    NodeLibrary,
    build_env,
    compile_source,
    parse,
    write,
)
from kohakunode.lower import PASSES, run_passes
from kohakunode.origins import stamp_origins
from kohakunode.sig.std import append
from kohakunode.syntax.ast import Call, Collect, walk

PREFIXES = [list(PASSES)[:count] for count in range(len(PASSES) + 1)]

CASES = {
    "empty": (
        "([])collect(_, _, `body`, None -> result)\nbody:\n",
        {"result": []},
    ),
    "empty_body": (
        "([1, 2, 3])collect(item, `body`, item -> result)\nbody:\n",
        {"result": [1, 2, 3], "item": 3},
    ),
    "literal_yield": (
        "([1, 2])collect(_, `body`, [7] -> result)\nbody:\n",
        {"result": [[7], [7]]},
    ),
    "carried": (
        "total = 0\n"
        "([1, 2, 3])collect(item, index, `body`, value -> result)\n"
        "body:\n"
        "    (total, item)add(total)\n"
        "    (total, index)add(value)\n",
        {"result": [sum(range(1, item + 1)) + item - 1 for item in [1, 2, 3]], "total": 6},
    ),
    "branches": (
        "([1, 2, 3])collect(item, `body`, value -> result)\n"
        "body:\n"
        "    (item, 2)less(small)\n"
        "    (small)branch(`yes`, `no`)\n"
        "    yes:\n"
        "        value = item\n"
        "    no:\n"
        "        (item, 10)add(value)\n",
        {"result": [1, 12, 13]},
    ),
    "nested": (
        "([2, 0, 3])collect(count, outer_index, `outer`, row -> result)\n"
        "outer:\n"
        "    (count)range(items)\n"
        "    (items)collect(item, inner_index, `inner`, item -> row)\n"
        "    inner:\n",
        {"result": [list(range(count)) for count in [2, 0, 3]]},
    ),
    "nested_each": (
        "([1, 2])collect(item, `outer`, total -> result)\n"
        "outer:\n"
        "    total = 0\n"
        "    ([10, 20])each(value, `inner`)\n"
        "    inner:\n"
        "        (total, value)add(total)\n"
        "    (total, item)add(total)\n",
        {"result": [sum([10, 20]) + item for item in [1, 2]]},
    ),
    "inside_each": (
        "([1, 2])each(count, `outer`)\n"
        "outer:\n"
        "    (count)range(items)\n"
        "    (items)collect(item, `inner`, item -> result)\n"
        "    inner:\n",
        {"result": list(range(2))},
    ),
    "namespace_before": (
        "body:\n" "    (item, 2)mul(value)\n" "([1, 2])collect(item, `body`, value -> result)\n",
        {"result": [item * 2 for item in [1, 2]]},
    ),
    "intervening": (
        "([1, 2])collect(item, `body`, item -> result)\n" "seen = result\n" "body:\n",
        {"result": [1, 2], "seen": [1, 2]},
    ),
    "repeat_def": (
        "@def (items)g(result):\n"
        "    (items)collect(item, `body`, value -> result)\n"
        "    body:\n"
        "        (item, 1)add(value)\n"
        "([1, 2])g(first)\n"
        "([3, 4])g(second)\n",
        {"first": [2, 3], "second": [4, 5]},
    ),
}


def prepared(source, libraries=()):
    program = stamp_origins(parse(source))
    return program, build_env(program, list(libraries), internal=True)


def execute(source, passes, libraries=(), hook=None, nodes=None):
    program, env = prepared(source, libraries)
    lowered = run_passes(program, env, passes)
    interpreter = Interpreter(lowered, env, nodes=nodes, hook=hook)
    interpreter.run()
    return interpreter, lowered


@pytest.mark.parametrize("passes", PREFIXES)
@pytest.mark.parametrize("case", CASES)
def test_collect_matches_every_lowering_prefix(case, passes):
    source, expected = CASES[case]
    reference, _ = execute(source, [])
    result, _ = execute(source, passes)
    assert result.source_values() == reference.source_values()
    assert {key: result.source_values()[key] for key in expected} == expected


FAILURES = NodeLibrary("collect_failures")


@FAILURES.node(outputs=["value"])
def checked(value: int) -> int:
    if value == 2:
        raise ValueError("second item fails")
    return value


LOCAL_CATCH = """([1, 2, 3])collect(item, `body`, value -> result)
body:
    @try:
        (item)checked(value)
    @except error:
        value = -1
"""

ESCAPING = """result = ["previous"]
marker = 0
@try:
    ([1, 2, 3])collect(item, `body`, value -> result)
    body:
        marker = item
        (item)checked(value)
@except error:
    saved = result
after = marker
"""


@pytest.mark.parametrize("passes", PREFIXES)
def test_local_catch_yields_but_escaping_failure_does_not_publish(passes):
    caught, _ = execute(LOCAL_CATCH, passes, [FAILURES])
    assert caught.source_values()["result"] == [1, -1, 3]
    escaping, _ = execute(ESCAPING, passes, [FAILURES])
    values = escaping.source_values()
    assert values["result"] == values["saved"] == ["previous"]
    assert values["after"] == values["marker"] == 2
    assert values["error"]["kind"] == "ValueError"
    assert set(values["error"]) == {"kind", "node", "message"}


@pytest.mark.parametrize("passes", PREFIXES)
def test_uncaught_failure_leaves_target_and_prior_body_writes(passes):
    source = (
        'result = ["previous"]\n'
        "([1, 2, 3])collect(item, `body`, value -> result)\n"
        "body:\n"
        "    marker = item\n"
        "    (item)checked(value)\n"
    )
    program, env = prepared(source, [FAILURES])
    interpreter = Interpreter(run_passes(program, env, passes), env)
    with pytest.raises(NodeFailure, match="second item fails"):
        interpreter.run()
    assert interpreter.source_values()["result"] == ["previous"]
    assert interpreter.source_values()["marker"] == 2
    assert interpreter.source_values()["value"] == 1


def test_collect_restarts_after_caught_failure_on_later_outer_iteration():
    source = (
        "([[1, 2], [3, 4]])each(items, `outer`)\n"
        "outer:\n"
        "    @try:\n"
        "        (items)collect(item, `inner`, value -> result)\n"
        "        inner:\n"
        "            (item)checked(value)\n"
        "    @except error:\n"
        "        result = []\n"
    )
    for passes in PREFIXES:
        interpreter, _ = execute(source, passes, [FAILURES])
        assert interpreter.source_values()["result"] == [3, 4]


def test_retains_yield_references_without_deepcopy_and_eagerly_snapshots_input():
    events = []
    payloads = [{"index": 0}, {"index": 1}]
    library = NodeLibrary("snapshot")

    @library.node(outputs=["items"])
    def source() -> Any:
        def values():
            for payload in payloads:
                events.append("input")
                yield payload

        return values()

    @library.node(outputs=["value"])
    def visit(value: Any) -> Any:
        events.append("body")
        return value

    text = "()source(items)\n(items)collect(item, `body`, value -> result)\nbody:\n    (item)visit(value)\n"
    for passes in PREFIXES:
        events.clear()
        interpreter, _ = execute(text, passes, [library])
        result = interpreter.source_values()["result"]
        assert events == ["input", "input", "body", "body"]
        assert result is not payloads
        assert all(got is original for got, original in zip(result, payloads))


def test_direct_collect_does_not_call_hooks_for_administration():
    seen = []

    def hook(name, inputs, call):
        seen.append(name)
        return call()

    source = "([1, 2])collect(item, `body`, value -> result)\nbody:\n    (item)identity(value)\n"
    execute(source, ["order_dataflow", "inline", "strip_meta"], hook=hook)
    assert seen == ["identity", "identity"]
    seen.clear()
    execute(source, ["expand_collect"], hook=hook)
    assert seen == [
        "kir.collect_items",
        "identity",
        "kir.collect_append",
        "identity",
        "kir.collect_append",
    ]


class CaptureCounter(Interpreter):
    """Test-only observation of private builder identity and normal-completion placements."""

    captures = 0

    def _exec(self, stmt, pos, each_state, resume_each, collected):
        builder = (
            collected[id(stmt)] if isinstance(stmt, Collect) and id(stmt) in resume_each else None
        )
        before = len(builder) if builder is not None else 0
        result = super()._exec(stmt, pos, each_state, resume_each, collected)
        if builder is not None:
            assert len(builder) == before + 1
            after = collected.get(id(stmt), self.scope.values.get(stmt.target))
            assert after is builder  # no fresh prefix copy, including final publication
            self.captures += 1
        return result


def accumulation_work(source):
    """Count logical list-element placements, not walltime or Python allocator capacity."""
    copied_lengths = []

    def tracked_append(items, item):
        result = append(items, item)
        assert result is not items
        copied_lengths.append(len(result))  # old prefix plus the one new reference
        return result

    program, env = prepared(source)
    direct = CaptureCounter(program, env, nodes={"kir.collect_append": tracked_append})
    direct.run()
    assert copied_lengths == []
    baseline, _ = execute(source, ["expand_collect"], nodes={"kir.collect_append": tracked_append})
    assert direct.source_values() == baseline.source_values()
    return direct, copied_lengths


@pytest.mark.parametrize("count", [0, 1, 4, 32])
def test_baseline_copy_work_is_explicit_and_direct_builder_has_linear_placements(count):
    source = f"({count})range(items)\n(items)collect(item, `body`, item -> result)\nbody:\n"
    direct, copied_lengths = accumulation_work(source)
    assert direct.captures == count
    assert copied_lengths == list(range(1, count + 1))
    assert sum(copied_lengths) == count * (count + 1) // 2
    assert direct.source_values()["result"] == list(range(count))


@pytest.mark.parametrize("counts", [[], [0], [2, 0, 3]])
def test_nested_allocation_counts_sum_each_independent_builder(counts):
    source = (
        f"({counts!r})collect(count, `outer`, row -> result)\n"
        "outer:\n"
        "    (count)range(items)\n"
        "    (items)collect(item, `inner`, item -> row)\n"
        "    inner:\n"
    )
    direct, copied_lengths = accumulation_work(source)
    sizes = [len(counts), *counts]
    assert direct.captures == sum(sizes)
    assert len(copied_lengths) == sum(sizes)
    assert sum(copied_lengths) == sum(size * (size + 1) // 2 for size in sizes)
    assert direct.source_values()["result"] == [list(range(count)) for count in counts]


def test_baseline_internal_append_cannot_be_shadowed_by_user_definition_or_host():
    source = (
        '@def (items, item)append(value):\n    value = ["wrong"]\n'
        "([1, 2])collect(item, `body`, item -> result)\nbody:\n"
    )
    for passes in PREFIXES:
        interpreter, _ = execute(source, passes)
        assert interpreter.source_values()["result"] == [1, 2]
    shadow = NodeLibrary("shadow")
    shadow.add("append", lambda items, item: ["wrong"], outputs=["value"])
    interpreter, _ = execute(CASES["empty_body"][0], list(PASSES), [shadow])
    assert interpreter.source_values()["result"] == [1, 2, 3]


def test_private_accumulator_names_are_hygienic_and_target_published_after_owner():
    source = "collect__1__values = 99\n" + CASES["intervening"][0]
    interpreter, lowered = execute(source, ["expand_collect"])
    assert interpreter.scope.values["collect__1__values"] == 99
    assert interpreter.scope.values["collect__2__values"] == [1, 2]
    assert interpreter.source_values()["seen"] == [1, 2]
    assert "collect(" not in write(lowered)


def test_legacy_pass_lists_remain_valid_and_collect_requires_expansion_only_when_needed():
    source = CASES["empty_body"][0]
    interpreter, preserved = execute(source, ["order_dataflow", "inline", "strip_meta"])
    assert any(isinstance(stmt, Collect) for stmt in walk(preserved.body))
    assert interpreter.source_values()["result"] == [1, 2, 3]
    for names in (["expand_each"], ["order_dataflow", "inline", "expand_each", "version"]):
        p, env = prepared(source)
        with pytest.raises(ValueError, match="expand_collect"):
            run_passes(p, env, names)
        legacy, _ = execute("x = 1\n", names)
        assert legacy.source_values()["x"] == 1


def test_expansion_is_idempotent_preserves_original_and_roundtrips_as_internal_text():
    p, env = prepared(CASES["nested"][0])
    once = run_passes(p, env, ["expand_collect"])
    twice = run_passes(once, env, ["expand_collect"])
    assert write(once) == write(twice)
    assert any(isinstance(stmt, Collect) for stmt in walk(p.body))
    assert not any(isinstance(stmt, Collect) for stmt in walk(once.body))
    rebuilt = parse(write(once))
    interpreter = Interpreter(rebuilt, build_env(rebuilt, internal=True))
    interpreter.run()
    assert interpreter.source_values()["result"] == CASES["nested"][1]["result"]
    assert (
        len([s for s in walk(once.body) if isinstance(s, Call) and s.name == "kir.collect_append"])
        == 2
    )


def test_exception_binding_does_not_collide_with_private_accumulator():
    source = LOCAL_CATCH.replace("@except error:", "@except collect__1__values:")
    for passes in PREFIXES:
        interpreter, _ = execute(source, passes, [FAILURES])
        assert interpreter.source_values()["result"] == [1, -1, 3]


class Payload:
    pass


@pytest.mark.parametrize("caught", [False, True])
@pytest.mark.parametrize("budget", [None, 2])
def test_abandoned_builder_releases_prior_yield_references(caught, budget):
    references = []
    library = NodeLibrary("release")

    @library.node(outputs=["value"])
    def make(item: int) -> Any:
        if item == 2:
            raise ValueError("stop")
        value = Payload()
        references.append(weakref.ref(value))
        return value

    @library.node(outputs=[])
    def probe() -> None:
        gc.collect()
        assert references[0]() is None
        assert references[1]() is not None  # last body write remains visible

    source = (
        "([0, 1, 2])collect(item, `body`, value -> result)\n" "body:\n" "    (item)make(value)\n"
    )
    if caught:
        source = "@try:\n" + "".join("    " + line + "\n" for line in source.splitlines())
        source += "@except error:\n    ()probe()\n"
    program, env = prepared(source, [library])
    interpreter = Interpreter(program, env, step_budget=budget)
    if caught and budget is None:
        interpreter.run()
    else:
        with pytest.raises(KirRuntimeError if budget is not None else NodeFailure):
            interpreter.run()
        probe()
    assert "result" not in interpreter.source_values()


def test_nested_failure_releases_inner_builder_but_keeps_enclosing_collect():
    inner_refs, outer_refs = [], []
    library = NodeLibrary("nested_release")

    @library.node(outputs=["value"])
    def inner(item: int) -> Any:
        if item == 2:
            raise ValueError("stop inner")
        value = Payload()
        inner_refs.append(weakref.ref(value))
        return value

    @library.node(outputs=["value"])
    def outer(item: int) -> Any:
        value = Payload()
        outer_refs.append(weakref.ref(value))
        return value

    @library.node(outputs=[])
    def probe() -> None:
        gc.collect()
        assert inner_refs[-2]() is None
        assert inner_refs[-1]() is not None
        assert outer_refs[0]() is not None

    source = (
        "([0, 1])collect(i, `outer_body`, outer_value -> result)\n"
        "outer_body:\n"
        "    (i)outer(outer_value)\n"
        "    @try:\n"
        "        ([0, 1, 2])collect(j, `inner_body`, inner_value -> discarded)\n"
        "        inner_body:\n"
        "            (j)inner(inner_value)\n"
        "    @except error:\n"
        "        ()probe()\n"
    )
    interpreter, _ = execute(source, [], [library])
    assert interpreter.source_values()["result"] == [reference() for reference in outer_refs]
    assert "discarded" not in interpreter.source_values()


class FinalizationProbe(Interpreter):
    fail_at_end = False
    ends = 0

    def _exec(self, stmt, pos, each_state, resume_each, collected):
        self.observed_collects = collected
        return super()._exec(stmt, pos, each_state, resume_each, collected)

    def _block_end(self, block, resume_each):
        self.ends += 1
        if self.fail_at_end and self.ends == 2:
            raise KirRuntimeError("injected control error outside _exec")
        return super()._block_end(block, resume_each)


@pytest.mark.parametrize("mode", ["success", "invalid_branch", "block_end_error"])
def test_collect_finally_clears_private_maps_without_clearing_published_lists(mode):
    body = "    value = item\n"
    if mode == "invalid_branch":
        body = (
            "    (item, 1)equal(first)\n"
            "    (first)branch(`ok`, `bad`)\n"
            "    ok:\n"
            "        value = item\n"
            "    bad:\n"
            "        (1)branch(`unreached_a`, `unreached_b`)\n"
            "        unreached_a:\n"
            "        unreached_b:\n"
        )
    source = 'result = ["previous"]\n([1, 2])collect(item, `body`, value -> result)\nbody:\n' + body
    program, env = prepared(source)
    interpreter = FinalizationProbe(program, env)
    interpreter.fail_at_end = mode == "block_end_error"
    if mode == "success":
        interpreter.run()
        assert interpreter.source_values()["result"] == [1, 2]
    else:
        with pytest.raises(KirRuntimeError):
            interpreter.run()
        assert interpreter.source_values()["result"] == ["previous"]
    assert interpreter.source_values()["item"] == 2
    assert interpreter.observed_collects == {}


class BrokenIterable:
    def __iter__(self):
        yield 1
        raise ValueError("snapshot failed")


@pytest.mark.parametrize("passes", PREFIXES)
@pytest.mark.parametrize(
    "bad_input", [42, BrokenIterable()], ids=["noniterable", "iterator_raises"]
)
def test_snapshot_failures_are_catchable_with_stable_internal_node(passes, bad_input):
    library = NodeLibrary("bad_input")
    library.add("source", lambda: bad_input, outputs=["items"])
    source = (
        'result = ["previous"]\n'
        "()source(items)\n"
        "@try:\n"
        "    (items)collect(item, `body`, item -> result)\n"
        "    body:\n"
        "@except error:\n"
        "    saved = result\n"
    )
    interpreter, _ = execute(source, passes, [library])
    values = interpreter.source_values()
    assert values["result"] == values["saved"] == ["previous"]
    assert values["error"]["node"] == "kir.collect_items"
    assert values["error"]["kind"] == ("TypeError" if type(bad_input) is int else "ValueError")
    reference, _ = execute(source, [], [library])
    assert values["error"] == reference.source_values()["error"]


def test_checked_compile_default_passes_support_collect():
    compiled = compile_source(CASES["branches"][0])
    interpreter = Interpreter(compiled.lowered, compiled.env)
    interpreter.run()
    assert interpreter.source_values()["result"] == CASES["branches"][1]["result"]
