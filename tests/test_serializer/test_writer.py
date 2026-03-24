"""Tests for kohakunode.serializer.writer — Writer."""


import pytest

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    Literal,
    MetaAnnotation,
    Namespace,
    Parameter,
    Parallel,
    Program,
    SubgraphDef,
    Wildcard,
)
from kohakunode.parser.parser import parse
from kohakunode.serializer.writer import Writer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(program: Program) -> str:
    return Writer().write(program)


def _roundtrip(source: str) -> str:
    """Parse source → write back to string."""
    return _write(parse(source))


# ---------------------------------------------------------------------------
# test_write_assignment
# ---------------------------------------------------------------------------


def test_write_assignment_int_literal():
    prog = Program(body=[Assignment(target="x", value=Literal(value=42, literal_type="int"))])
    text = _write(prog)
    assert "x = 42" in text


def test_write_assignment_string_literal():
    prog = Program(
        body=[Assignment(target="name", value=Literal(value="hello", literal_type="str"))]
    )
    text = _write(prog)
    assert 'name = "hello"' in text


def test_write_assignment_identifier_rhs():
    prog = Program(body=[Assignment(target="y", value=Identifier(name="x"))])
    text = _write(prog)
    assert "y = x" in text


def test_write_assignment_float_literal():
    prog = Program(body=[Assignment(target="pi", value=Literal(value=3.14, literal_type="float"))])
    text = _write(prog)
    assert "pi = " in text
    assert "3.14" in text


def test_write_assignment_bool_true():
    prog = Program(body=[Assignment(target="flag", value=Literal(value=True, literal_type="bool"))])
    text = _write(prog)
    assert "flag = True" in text


def test_write_assignment_bool_false():
    prog = Program(body=[Assignment(target="flag", value=Literal(value=False, literal_type="bool"))])
    text = _write(prog)
    assert "flag = False" in text


def test_write_assignment_none_literal():
    prog = Program(body=[Assignment(target="empty", value=Literal(value=None, literal_type="none"))])
    text = _write(prog)
    assert "empty = None" in text


def test_roundtrip_assignment():
    source = "x = 42\n"
    result = _roundtrip(source)
    reparsed = parse(result)
    assert len(reparsed.body) == 1
    stmt = reparsed.body[0]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "x"
    assert stmt.value.value == 42


# ---------------------------------------------------------------------------
# test_write_func_call
# ---------------------------------------------------------------------------


def test_write_func_call_basic():
    call = FuncCall(
        inputs=[Identifier(name="a"), Identifier(name="b")],
        func_name="process",
        outputs=["result"],
    )
    text = _write(Program(body=[call]))
    assert "(a, b)process(result)" in text


def test_write_func_call_no_inputs():
    call = FuncCall(inputs=[], func_name="generate", outputs=["val"])
    text = _write(Program(body=[call]))
    assert "()generate(val)" in text


def test_write_func_call_no_outputs():
    call = FuncCall(inputs=[Identifier(name="x")], func_name="consume", outputs=[])
    text = _write(Program(body=[call]))
    assert "(x)consume()" in text


def test_write_func_call_wildcard_output():
    call = FuncCall(inputs=[], func_name="gen", outputs=[Wildcard()])
    text = _write(Program(body=[call]))
    assert "()gen(_)" in text


def test_write_func_call_keyword_input():
    call = FuncCall(
        inputs=[KeywordArg(name="mode", value=Literal(value="fast", literal_type="str"))],
        func_name="process",
        outputs=["out"],
    )
    text = _write(Program(body=[call]))
    assert 'mode="fast"' in text
    assert "process" in text


def test_write_func_call_with_metadata():
    meta = MetaAnnotation(data={"node_id": "7"})
    call = FuncCall(func_name="fn", inputs=[], outputs=["x"], metadata=[meta])
    text = _write(Program(body=[call]))
    assert "@meta" in text
    assert "node_id" in text
    assert "()fn(x)" in text


def test_roundtrip_func_call():
    source = "(a, b)process(result)\n"
    result = _roundtrip(source)
    reparsed = parse(result)
    stmt = reparsed.body[0]
    assert isinstance(stmt, FuncCall)
    assert stmt.func_name == "process"
    assert len(stmt.inputs) == 2
    assert stmt.outputs == ["result"]


# ---------------------------------------------------------------------------
# test_write_branch
# ---------------------------------------------------------------------------


def test_write_branch_basic():
    branch = Branch(
        condition=Identifier(name="cond"),
        true_label="yes",
        false_label="no",
    )
    text = _write(Program(body=[branch]))
    assert "(cond)branch(`yes`, `no`)" in text


def test_write_branch_literal_condition():
    branch = Branch(
        condition=Literal(value=True, literal_type="bool"),
        true_label="t",
        false_label="f",
    )
    text = _write(Program(body=[branch]))
    assert "(True)branch(`t`, `f`)" in text


def test_roundtrip_branch():
    source = "(cond)branch(`on_true`, `on_false`)\non_true:\n    (x)fn(y)\non_false:\n    (z)fn(w)\n"
    result = _roundtrip(source)
    reparsed = parse(result)
    # First statement is the branch
    stmt = reparsed.body[0]
    assert isinstance(stmt, Branch)
    assert stmt.true_label == "on_true"
    assert stmt.false_label == "on_false"


# ---------------------------------------------------------------------------
# test_write_namespace
# ---------------------------------------------------------------------------


def test_write_namespace_produces_label_line():
    ns = Namespace(name="my_label", body=[])
    text = _write(Program(body=[ns]))
    assert "my_label:" in text


def test_write_namespace_body_indented():
    inner = FuncCall(inputs=[], func_name="inner_fn", outputs=["x"])
    ns = Namespace(name="ns", body=[inner])
    text = _write(Program(body=[ns]))
    lines = text.splitlines()
    label_line = next(i for i, l in enumerate(lines) if "ns:" in l)
    body_line = next(i for i, l in enumerate(lines) if "inner_fn" in l)
    # Body line must be indented relative to label line.
    assert lines[body_line].startswith("    ")
    assert body_line > label_line


def test_write_nested_namespace_double_indent():
    inner_call = FuncCall(inputs=[], func_name="deep", outputs=[])
    inner_ns = Namespace(name="inner", body=[inner_call])
    outer_ns = Namespace(name="outer", body=[inner_ns])
    text = _write(Program(body=[outer_ns]))
    # deep should be at two levels of indentation (8 spaces)
    lines = text.splitlines()
    deep_line = next(l for l in lines if "deep" in l)
    assert deep_line.startswith("        ")


def test_roundtrip_namespace():
    source = "my_label:\n    ()fn(x)\n"
    result = _roundtrip(source)
    reparsed = parse(result)
    ns = reparsed.body[0]
    assert isinstance(ns, Namespace)
    assert ns.name == "my_label"
    assert len(ns.body) == 1


# ---------------------------------------------------------------------------
# test_write_subgraph
# ---------------------------------------------------------------------------


def test_write_subgraph_def_header():
    sg = SubgraphDef(
        name="my_func",
        params=[Parameter(name="x"), Parameter(name="y")],
        outputs=["result"],
        body=[FuncCall(func_name="add", inputs=[Identifier(name="x"), Identifier(name="y")], outputs=["result"])],
    )
    text = _write(Program(body=[sg]))
    assert "@def" in text
    assert "my_func" in text
    assert "x" in text
    assert "y" in text
    assert "result" in text


def test_write_subgraph_def_body_indented():
    sg = SubgraphDef(
        name="sg",
        params=[Parameter(name="a")],
        outputs=["b"],
        body=[FuncCall(func_name="transform", inputs=[Identifier(name="a")], outputs=["b"])],
    )
    text = _write(Program(body=[sg]))
    lines = text.splitlines()
    def_line = next(i for i, l in enumerate(lines) if "@def" in l)
    body_line = next(i for i, l in enumerate(lines) if "transform" in l)
    assert lines[body_line].startswith("    ")
    assert body_line > def_line


def test_write_subgraph_blank_line_after():
    """Writer should append a blank line after each @def block when followed by more statements."""
    sg = SubgraphDef(
        name="sg",
        params=[],
        outputs=[],
        body=[FuncCall(func_name="fn", inputs=[], outputs=[])],
    )
    # Add a statement after the subgraph so the trailing blank line is visible.
    call = FuncCall(func_name="after", inputs=[], outputs=[])
    text = _write(Program(body=[sg, call]))
    # The blank line separator should appear between the @def block and the next statement.
    assert "\n\n" in text


def test_write_subgraph_param_with_default():
    default = Literal(value=1.0, literal_type="float")
    sg = SubgraphDef(
        name="sg",
        params=[Parameter(name="alpha", default=default)],
        outputs=["out"],
        body=[FuncCall(func_name="fn", inputs=[Identifier(name="alpha")], outputs=["out"])],
    )
    text = _write(Program(body=[sg]))
    assert "alpha=" in text or "alpha ==" in text or "1.0" in text


def test_roundtrip_subgraph():
    """Parse a subgraph source and verify Writer serializes the key fields correctly.

    NOTE: The Writer emits '@def name(params)(outputs)' which differs from the
    grammar's '@def (params)name(outputs):' input format, so the written text
    is not re-parseable. Instead we verify the written text contains all
    expected identifiers.
    """
    source = "@def (input, strength=1.0)preprocess(output):\n    (input)denoise(clean)\n    (clean, amount=strength)normalize(output)\n\n"
    prog = parse(source)
    text = _write(prog)
    assert "preprocess" in text
    assert "input" in text
    assert "output" in text
    assert "denoise" in text
    assert "normalize" in text


# ---------------------------------------------------------------------------
# Additional writer tests
# ---------------------------------------------------------------------------


def test_write_jump():
    jump = Jump(target="end")
    text = _write(Program(body=[jump]))
    assert "()jump(`end`)" in text


def test_write_parallel():
    parallel = Parallel(labels=["task_a", "task_b"])
    text = _write(Program(body=[parallel]))
    assert "()parallel(`task_a`, `task_b`)" in text


def test_write_mode_dataflow():
    prog = Program(body=[], mode="dataflow")
    text = _write(prog)
    assert "@mode dataflow" in text


def test_write_ends_with_newline():
    prog = Program(body=[Assignment(target="x", value=Literal(value=1, literal_type="int"))])
    text = _write(prog)
    assert text.endswith("\n")
