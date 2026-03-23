import pytest

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    Identifier,
    Jump,
    Literal,
    Namespace,
    Parallel,
    Switch,
)
from kohakunode.engine.builtins import (
    execute_branch,
    execute_jump,
    execute_parallel,
    execute_switch,
)
from kohakunode.engine.context import ExecutionContext
from kohakunode.errors import KirRuntimeError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context_with_statements(statements: list) -> ExecutionContext:
    """Create a context with a single frame containing *statements*."""
    ctx = ExecutionContext()
    ctx.push_frame(statements)
    return ctx


def _make_namespace(name: str, body: list | None = None) -> Namespace:
    return Namespace(name=name, body=body if body is not None else [])


def _assign_stmt(target: str, value) -> Assignment:
    return Assignment(target=target, value=Literal(value=value, literal_type="int"))


# ---------------------------------------------------------------------------
# test_branch_true
# ---------------------------------------------------------------------------


def test_branch_true():
    true_ns = _make_namespace("on_true", [_assign_stmt("result", 1)])
    false_ns = _make_namespace("on_false", [_assign_stmt("result", 0)])

    branch = Branch(
        condition=Literal(value=True, literal_type="bool"),
        true_label="on_true",
        false_label="on_false",
    )

    stmts = [branch, true_ns, false_ns]
    ctx = _make_context_with_statements(stmts)

    execute_branch(branch, ctx)

    # A new frame should have been pushed for the true namespace.
    assert ctx.current_frame.namespace_name == "on_true"
    assert ctx.current_frame.statements is true_ns.body


def test_branch_true_via_identifier():
    true_ns = _make_namespace("yes", [_assign_stmt("x", 10)])
    false_ns = _make_namespace("no", [_assign_stmt("x", 20)])

    branch = Branch(
        condition=Identifier(name="flag"),
        true_label="yes",
        false_label="no",
    )

    stmts = [branch, true_ns, false_ns]
    ctx = _make_context_with_statements(stmts)
    ctx.variables.set("flag", True)

    execute_branch(branch, ctx)

    assert ctx.current_frame.namespace_name == "yes"


# ---------------------------------------------------------------------------
# test_branch_false
# ---------------------------------------------------------------------------


def test_branch_false():
    true_ns = _make_namespace("on_true", [_assign_stmt("result", 1)])
    false_ns = _make_namespace("on_false", [_assign_stmt("result", 0)])

    branch = Branch(
        condition=Literal(value=False, literal_type="bool"),
        true_label="on_true",
        false_label="on_false",
    )

    stmts = [branch, true_ns, false_ns]
    ctx = _make_context_with_statements(stmts)

    execute_branch(branch, ctx)

    assert ctx.current_frame.namespace_name == "on_false"
    assert ctx.current_frame.statements is false_ns.body


def test_branch_false_via_identifier():
    true_ns = _make_namespace("yes", [_assign_stmt("x", 10)])
    false_ns = _make_namespace("no", [_assign_stmt("x", 20)])

    branch = Branch(
        condition=Identifier(name="flag"),
        true_label="yes",
        false_label="no",
    )

    stmts = [branch, true_ns, false_ns]
    ctx = _make_context_with_statements(stmts)
    ctx.variables.set("flag", False)

    execute_branch(branch, ctx)

    assert ctx.current_frame.namespace_name == "no"


# ---------------------------------------------------------------------------
# test_branch_non_bool
# ---------------------------------------------------------------------------


def test_branch_non_bool_integer_raises():
    true_ns = _make_namespace("on_true")
    false_ns = _make_namespace("on_false")

    branch = Branch(
        condition=Literal(value=1, literal_type="int"),
        true_label="on_true",
        false_label="on_false",
    )

    stmts = [branch, true_ns, false_ns]
    ctx = _make_context_with_statements(stmts)

    with pytest.raises(KirRuntimeError, match="bool"):
        execute_branch(branch, ctx)


def test_branch_non_bool_string_via_identifier_raises():
    true_ns = _make_namespace("on_true")
    false_ns = _make_namespace("on_false")

    branch = Branch(
        condition=Identifier(name="flag"),
        true_label="on_true",
        false_label="on_false",
    )

    stmts = [branch, true_ns, false_ns]
    ctx = _make_context_with_statements(stmts)
    ctx.variables.set("flag", "yes")

    with pytest.raises(KirRuntimeError, match="bool"):
        execute_branch(branch, ctx)


# ---------------------------------------------------------------------------
# test_switch_match
# ---------------------------------------------------------------------------


def test_switch_match_first_case():
    ns_a = _make_namespace("case_a", [_assign_stmt("chosen", 1)])
    ns_b = _make_namespace("case_b", [_assign_stmt("chosen", 2)])
    ns_c = _make_namespace("case_c", [_assign_stmt("chosen", 3)])

    switch = Switch(
        value=Literal(value="a", literal_type="str"),
        cases=[
            (Literal(value="a", literal_type="str"), "case_a"),
            (Literal(value="b", literal_type="str"), "case_b"),
        ],
        default_label="case_c",
    )

    stmts = [switch, ns_a, ns_b, ns_c]
    ctx = _make_context_with_statements(stmts)

    execute_switch(switch, ctx)

    assert ctx.current_frame.namespace_name == "case_a"


def test_switch_match_second_case():
    ns_a = _make_namespace("case_a")
    ns_b = _make_namespace("case_b", [_assign_stmt("chosen", 2)])

    switch = Switch(
        value=Identifier(name="val"),
        cases=[
            (Literal(value=1, literal_type="int"), "case_a"),
            (Literal(value=2, literal_type="int"), "case_b"),
        ],
        default_label=None,
    )

    stmts = [switch, ns_a, ns_b]
    ctx = _make_context_with_statements(stmts)
    ctx.variables.set("val", 2)

    execute_switch(switch, ctx)

    assert ctx.current_frame.namespace_name == "case_b"


# ---------------------------------------------------------------------------
# test_switch_default
# ---------------------------------------------------------------------------


def test_switch_default():
    ns_a = _make_namespace("case_a")
    ns_default = _make_namespace("fallback", [_assign_stmt("chosen", 99)])

    switch = Switch(
        value=Literal(value=42, literal_type="int"),
        cases=[
            (Literal(value=1, literal_type="int"), "case_a"),
        ],
        default_label="fallback",
    )

    stmts = [switch, ns_a, ns_default]
    ctx = _make_context_with_statements(stmts)

    execute_switch(switch, ctx)

    assert ctx.current_frame.namespace_name == "fallback"


def test_switch_no_match_no_default_raises():
    ns_a = _make_namespace("case_a")

    switch = Switch(
        value=Literal(value=99, literal_type="int"),
        cases=[
            (Literal(value=1, literal_type="int"), "case_a"),
        ],
        default_label=None,
    )

    stmts = [switch, ns_a]
    ctx = _make_context_with_statements(stmts)

    with pytest.raises(KirRuntimeError, match="no case matched"):
        execute_switch(switch, ctx)


# ---------------------------------------------------------------------------
# test_jump
# ---------------------------------------------------------------------------


def test_jump_pushes_target_frame():
    target_ns = _make_namespace("my_target", [_assign_stmt("jumped", 1)])
    jump = Jump(target="my_target")

    stmts = [jump, target_ns]
    ctx = _make_context_with_statements(stmts)

    execute_jump(jump, ctx)

    assert ctx.current_frame.namespace_name == "my_target"
    assert ctx.current_frame.statements is target_ns.body


def test_jump_target_not_found_raises():
    jump = Jump(target="ghost")

    stmts = [jump]
    ctx = _make_context_with_statements(stmts)

    with pytest.raises(KirRuntimeError, match="not found"):
        execute_jump(jump, ctx)


def test_jump_resolves_from_parent_frame():
    """A jump inside a nested frame can target a namespace in an outer frame."""
    outer_target = _make_namespace("outer_ns", [_assign_stmt("x", 7)])
    inner_jump = Jump(target="outer_ns")

    outer_stmts = [outer_target]
    inner_stmts = [inner_jump]

    ctx = ExecutionContext()
    ctx.push_frame(outer_stmts, namespace_name="root")
    ctx.push_frame(inner_stmts, namespace_name="inner")

    execute_jump(inner_jump, ctx)

    assert ctx.current_frame.namespace_name == "outer_ns"


# ---------------------------------------------------------------------------
# test_parallel
# ---------------------------------------------------------------------------


def test_parallel_runs_all_bodies():
    executed = []

    def run_body(stmts):
        executed.append(stmts)

    ns_a = _make_namespace("branch_a", [_assign_stmt("a", 1)])
    ns_b = _make_namespace("branch_b", [_assign_stmt("b", 2)])

    parallel = Parallel(labels=["branch_a", "branch_b"])

    stmts = [parallel, ns_a, ns_b]
    ctx = _make_context_with_statements(stmts)

    execute_parallel(parallel, ctx, run_body)

    assert len(executed) == 2
    assert ns_a.body in executed
    assert ns_b.body in executed


def test_parallel_order_preserved():
    order = []

    def run_body(stmts):
        # Each body is a list with one assignment; record the target name.
        order.append(stmts[0].target)

    ns_x = _make_namespace("x_ns", [_assign_stmt("x_ran", 1)])
    ns_y = _make_namespace("y_ns", [_assign_stmt("y_ran", 2)])
    ns_z = _make_namespace("z_ns", [_assign_stmt("z_ran", 3)])

    parallel = Parallel(labels=["x_ns", "y_ns", "z_ns"])
    stmts = [parallel, ns_x, ns_y, ns_z]
    ctx = _make_context_with_statements(stmts)

    execute_parallel(parallel, ctx, run_body)

    assert order == ["x_ran", "y_ran", "z_ran"]


def test_parallel_missing_label_raises():
    parallel = Parallel(labels=["missing_ns"])
    stmts = [parallel]
    ctx = _make_context_with_statements(stmts)

    with pytest.raises(KirRuntimeError, match="not found"):
        execute_parallel(parallel, ctx, lambda body: None)
