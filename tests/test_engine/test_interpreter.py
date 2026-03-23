import pytest

from kohakunode.engine.interpreter import Interpreter
from kohakunode.engine.registry import Registry
from kohakunode.errors import KirRuntimeError
from kohakunode.parser.parser import parse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(**extra) -> Registry:
    """Return a Registry pre-loaded with common test functions."""
    registry = Registry()
    registry.register("add", lambda a, b: a + b, output_names=["result"])
    registry.register("less_than", lambda a, b: a < b, output_names=["result"])
    for name, (func, out) in extra.items():
        registry.register(name, func, output_names=out)
    return registry


def _run(source: str, registry: Registry | None = None) -> dict:
    """Parse *source*, run it with *registry*, return a variable snapshot."""
    if registry is None:
        registry = Registry()
    interp = Interpreter(registry)
    interp.run(parse(source))
    return interp.context.variables.snapshot()


# ---------------------------------------------------------------------------
# test_assignment
# ---------------------------------------------------------------------------


def test_assignment_integer():
    result = _run("x = 42")
    assert result["x"] == 42


def test_assignment_string():
    result = _run('name = "world"')
    assert result["name"] == "world"


def test_assignment_float():
    result = _run("pi = 3.14")
    assert result["pi"] == pytest.approx(3.14)


def test_assignment_bool():
    result = _run("flag = True")
    assert result["flag"] is True


def test_assignment_none():
    result = _run("empty = None")
    assert result["empty"] is None


def test_assignment_identifier():
    """Assigning one variable's value to another."""
    result = _run("x = 10\ny = x")
    assert result["y"] == 10


def test_assignment_multiple():
    source = "a = 1\nb = 2\nc = 3"
    result = _run(source)
    assert result["a"] == 1
    assert result["b"] == 2
    assert result["c"] == 3


# ---------------------------------------------------------------------------
# test_func_call
# ---------------------------------------------------------------------------


def test_func_call_add():
    registry = _make_registry()
    result = _run("x = 3\ny = 4\n(x, y)add(sum_val)", registry)
    assert result["sum_val"] == 7


def test_func_call_output_assigned():
    registry = _make_registry()
    result = _run("(10, 20)add(total)", registry)
    assert result["total"] == 30


def test_func_call_chained():
    registry = _make_registry()
    source = "(1, 2)add(a)\n(a, 3)add(b)"
    result = _run(source, registry)
    assert result["a"] == 3
    assert result["b"] == 6


def test_func_call_no_output():
    """A func call with no output target should not raise."""
    registry = Registry()
    registry.register("noop", lambda: None, output_names=[])
    _run("()noop()", registry)  # Should complete without error.


# ---------------------------------------------------------------------------
# test_namespace_skip
# ---------------------------------------------------------------------------


def test_namespace_skip():
    """A bare namespace block is skipped during sequential execution."""
    registry = Registry()
    registry.register("process", lambda x: x * 2, output_names=["result"])

    source = (
        "x = 1\n"
        "unused:\n"
        '    ("never")process(never_set)\n'
        "(x)process(result)"
    )
    result = _run(source, registry)

    assert result["x"] == 1
    assert result["result"] == 2
    assert "never_set" not in result


def test_namespace_skip_multiple():
    source = (
        "val = 5\n"
        "alpha:\n"
        "    ignored = 99\n"
        "beta:\n"
        "    ignored2 = 100\n"
        "final = val"
    )
    result = _run(source)

    assert result["val"] == 5
    assert result["final"] == 5
    assert "ignored" not in result
    assert "ignored2" not in result


# ---------------------------------------------------------------------------
# test_branch_execution
# ---------------------------------------------------------------------------


def test_branch_true_path():
    registry = _make_registry()
    source = (
        "cond = True\n"
        "(cond)branch(`yes`, `no`)\n"
        "yes:\n"
        "    result = 1\n"
        "no:\n"
        "    result = 0"
    )
    result = _run(source, registry)
    assert result["result"] == 1


def test_branch_false_path():
    registry = _make_registry()
    source = (
        "cond = False\n"
        "(cond)branch(`yes`, `no`)\n"
        "yes:\n"
        "    result = 1\n"
        "no:\n"
        "    result = 0"
    )
    result = _run(source, registry)
    assert result["result"] == 0


def test_branch_with_func_result():
    registry = _make_registry()
    source = (
        "a = 3\n"
        "b = 5\n"
        "(a, b)less_than(cond)\n"
        "(cond)branch(`smaller`, `bigger`)\n"
        "smaller:\n"
        "    outcome = 1\n"
        "bigger:\n"
        "    outcome = 0"
    )
    result = _run(source, registry)
    assert result["outcome"] == 1


# ---------------------------------------------------------------------------
# test_loop
# ---------------------------------------------------------------------------


def test_loop_counter_0_to_5():
    """Counter loop: start at 0, increment by 1, stop when counter >= 5."""
    registry = _make_registry()
    source = (
        "counter = 0\n"
        "limit = 5\n"
        "()jump(`loop_body`)\n"
        "loop_body:\n"
        "    (counter, 1)add(counter)\n"
        "    (counter, limit)less_than(keep_going)\n"
        "    (keep_going)branch(`continue_loop`, `exit_loop`)\n"
        "    continue_loop:\n"
        "        ()jump(`loop_body`)\n"
        "    exit_loop:"
    )
    result = _run(source, registry)
    assert result["counter"] == 5


def test_loop_counter_accumulates():
    """Loop runs exactly N times: verify counter value matches expected N."""
    registry = _make_registry()
    source = (
        "counter = 0\n"
        "limit = 3\n"
        "()jump(`loop_body`)\n"
        "loop_body:\n"
        "    (counter, 1)add(counter)\n"
        "    (counter, limit)less_than(keep_going)\n"
        "    (keep_going)branch(`continue_loop`, `exit_loop`)\n"
        "    continue_loop:\n"
        "        ()jump(`loop_body`)\n"
        "    exit_loop:"
    )
    result = _run(source, registry)
    assert result["counter"] == 3


# ---------------------------------------------------------------------------
# test_subgraph
# ---------------------------------------------------------------------------


def test_subgraph_basic():
    registry = Registry()
    registry.register("double", lambda x: x * 2, output_names=["result"])

    source = (
        "@def (n)compute(out):\n"
        "    (n)double(out)\n"
        "\n"
        "(5)compute(answer)"
    )
    result = _run(source, registry)
    assert result["answer"] == 10


def test_subgraph_with_default_param():
    registry = Registry()
    registry.register(
        "scale", lambda x, factor: x * factor, output_names=["result"]
    )

    source = (
        "@def (x, factor=2)scale_it(result):\n"
        "    (x, factor)scale(result)\n"
        "\n"
        "(3)scale_it(r1)\n"
        "(3, factor=4)scale_it(r2)"
    )
    result = _run(source, registry)
    assert result["r1"] == 6
    assert result["r2"] == 12


def test_subgraph_multiple_outputs():
    registry = Registry()
    registry.register(
        "add_sub", lambda a, b: (a + b, a - b), output_names=["s", "d"]
    )

    source = (
        "@def (a, b)both(s, d):\n"
        "    (a, b)add_sub(s, d)\n"
        "\n"
        "(10, 3)both(total, diff)"
    )
    result = _run(source, registry)
    assert result["total"] == 13
    assert result["diff"] == 7


# ---------------------------------------------------------------------------
# test_parallel
# ---------------------------------------------------------------------------


def test_parallel_all_branches_run():
    registry = Registry()
    registry.register("increment", lambda x: x + 1, output_names=["result"])

    source = (
        "a = 0\n"
        "b = 0\n"
        "()parallel(`inc_a`, `inc_b`)\n"
        "inc_a:\n"
        "    (a)increment(a)\n"
        "inc_b:\n"
        "    (b)increment(b)"
    )
    result = _run(source, registry)
    assert result["a"] == 1
    assert result["b"] == 1


def test_parallel_three_branches():
    registry = Registry()
    registry.register("set_flag", lambda: True, output_names=["result"])

    source = (
        "()parallel(`p1`, `p2`, `p3`)\n"
        "p1:\n"
        "    flag1 = 1\n"
        "p2:\n"
        "    flag2 = 2\n"
        "p3:\n"
        "    flag3 = 3"
    )
    result = _run(source, registry)
    assert result["flag1"] == 1
    assert result["flag2"] == 2
    assert result["flag3"] == 3


def test_parallel_shared_variable_last_write_wins():
    """When two parallel branches write the same variable, the last one wins."""
    source = (
        "()parallel(`first`, `second`)\n"
        "first:\n"
        "    shared = 1\n"
        "second:\n"
        "    shared = 2"
    )
    result = _run(source)
    # Sequential execution: second branch runs after first, so shared == 2.
    assert result["shared"] == 2
