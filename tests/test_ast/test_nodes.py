"""Tests for kohakunode.ast.nodes — AST node construction and field access."""


import pytest

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    LabelRef,
    Literal,
    MetaAnnotation,
    ModeDecl,
    Namespace,
    Parallel,
    Parameter,
    Program,
    Statement,
    SubgraphDef,
    Switch,
    Wildcard,
)


# ---------------------------------------------------------------------------
# test_create_program
# ---------------------------------------------------------------------------


def test_create_program_empty():
    prog = Program()
    assert prog.body == []
    assert prog.mode is None
    assert prog.line is None


def test_create_program_with_body():
    stmt = Assignment(target="x", value=Literal(value=1, literal_type="int"))
    prog = Program(body=[stmt])
    assert len(prog.body) == 1
    assert prog.body[0] is stmt


def test_create_program_dataflow_mode():
    prog = Program(body=[], mode="dataflow")
    assert prog.mode == "dataflow"


# ---------------------------------------------------------------------------
# test_create_assignment
# ---------------------------------------------------------------------------


def test_create_assignment_fields():
    val = Literal(value=42, literal_type="int")
    node = Assignment(target="my_var", value=val)
    assert node.target == "my_var"
    assert node.value is val
    assert node.line is None


def test_create_assignment_with_line():
    val = Identifier(name="x")
    node = Assignment(target="y", value=val, line=7)
    assert node.line == 7


def test_create_assignment_default_value():
    # default_factory produces an Identifier()
    node = Assignment(target="z")
    assert isinstance(node.value, Identifier)


# ---------------------------------------------------------------------------
# test_create_func_call
# ---------------------------------------------------------------------------


def test_create_func_call_fields():
    inp1 = Identifier(name="a")
    inp2 = Literal(value=3.0, literal_type="float")
    node = FuncCall(inputs=[inp1, inp2], func_name="my_func", outputs=["result"])
    assert node.func_name == "my_func"
    assert node.inputs == [inp1, inp2]
    assert node.outputs == ["result"]
    assert node.metadata is None


def test_create_func_call_defaults():
    node = FuncCall()
    assert node.inputs == []
    assert node.func_name == ""
    assert node.outputs == []
    assert node.metadata is None


def test_create_func_call_with_wildcard_output():
    wc = Wildcard()
    node = FuncCall(func_name="gen", inputs=[], outputs=[wc])
    assert isinstance(node.outputs[0], Wildcard)


def test_create_func_call_with_metadata():
    meta = MetaAnnotation(data={"node_id": "42"})
    node = FuncCall(func_name="fn", metadata=[meta])
    assert node.metadata is not None
    assert len(node.metadata) == 1
    assert node.metadata[0].data["node_id"] == "42"


def test_create_func_call_with_keyword_input():
    kw = KeywordArg(name="mode", value=Literal(value="fast", literal_type="str"))
    node = FuncCall(func_name="process", inputs=[kw], outputs=["out"])
    assert isinstance(node.inputs[0], KeywordArg)
    assert node.inputs[0].name == "mode"


# ---------------------------------------------------------------------------
# test_literal_types
# ---------------------------------------------------------------------------


def test_literal_int():
    node = Literal(value=10, literal_type="int")
    assert node.value == 10
    assert node.literal_type == "int"


def test_literal_float():
    node = Literal(value=3.14, literal_type="float")
    assert node.literal_type == "float"
    assert abs(node.value - 3.14) < 1e-9


def test_literal_str():
    node = Literal(value="hello", literal_type="str")
    assert node.literal_type == "str"
    assert node.value == "hello"


def test_literal_bool_true():
    node = Literal(value=True, literal_type="bool")
    assert node.literal_type == "bool"
    assert node.value is True


def test_literal_bool_false():
    node = Literal(value=False, literal_type="bool")
    assert node.value is False


def test_literal_none():
    node = Literal(value=None, literal_type="none")
    assert node.literal_type == "none"
    assert node.value is None


def test_literal_list():
    items = [Literal(value=1, literal_type="int"), Literal(value=2, literal_type="int")]
    node = Literal(value=items, literal_type="list")
    assert node.literal_type == "list"
    assert len(node.value) == 2


def test_literal_dict():
    # Dict literals store key/value pairs; use plain Python values here since
    # dataclasses are unhashable by default.  The dict is opaque data inside
    # a Literal node — the Writer handles the actual key/value serialization.
    pairs = {"key": Literal(value=1, literal_type="int")}
    node = Literal(value=pairs, literal_type="dict")
    assert node.literal_type == "dict"
    assert "key" in node.value


# ---------------------------------------------------------------------------
# test_line_numbers
# ---------------------------------------------------------------------------


def test_line_number_assignment():
    node = Assignment(target="x", value=Identifier(name="y"), line=5)
    assert node.line == 5


def test_line_number_func_call():
    node = FuncCall(func_name="f", line=12)
    assert node.line == 12


def test_line_number_branch():
    node = Branch(
        condition=Identifier(name="cond"),
        true_label="yes",
        false_label="no",
        line=3,
    )
    assert node.line == 3


def test_line_number_namespace():
    node = Namespace(name="my_ns", body=[], line=20)
    assert node.line == 20


def test_line_number_program():
    node = Program(body=[], line=1)
    assert node.line == 1


def test_line_number_defaults_none():
    node = Literal(value=0, literal_type="int")
    assert node.line is None


def test_line_number_identifier():
    node = Identifier(name="x", line=99)
    assert node.line == 99


# ---------------------------------------------------------------------------
# Miscellaneous node construction
# ---------------------------------------------------------------------------


def test_create_jump():
    node = Jump(target="done", line=8)
    assert node.target == "done"
    assert node.line == 8


def test_create_parallel():
    node = Parallel(labels=["task_a", "task_b"])
    assert node.labels == ["task_a", "task_b"]


def test_create_namespace_with_body():
    inner = FuncCall(func_name="do_thing", line=2)
    ns = Namespace(name="my_label", body=[inner], line=1)
    assert ns.name == "my_label"
    assert len(ns.body) == 1
    assert ns.body[0] is inner


def test_create_subgraph_def():
    params = [Parameter(name="x"), Parameter(name="y")]
    body = [FuncCall(func_name="add", inputs=[Identifier(name="x"), Identifier(name="y")], outputs=["result"])]
    sg = SubgraphDef(name="my_subgraph", params=params, outputs=["result"], body=body)
    assert sg.name == "my_subgraph"
    assert len(sg.params) == 2
    assert sg.outputs == ["result"]


def test_create_parameter_with_default():
    default_val = Literal(value=1.0, literal_type="float")
    param = Parameter(name="alpha", default=default_val)
    assert param.name == "alpha"
    assert param.default is default_val


def test_create_parameter_no_default():
    param = Parameter(name="x")
    assert param.default is None


def test_create_switch():
    node = Switch(
        value=Identifier(name="val"),
        cases=[(Literal(value=0, literal_type="int"), "case_zero")],
        default_label="fallthrough",
    )
    assert len(node.cases) == 1
    assert node.default_label == "fallthrough"


def test_create_label_ref():
    node = LabelRef(name="target_ns")
    assert node.name == "target_ns"


def test_create_mode_decl():
    node = ModeDecl(mode="dataflow")
    assert node.mode == "dataflow"


def test_create_wildcard():
    wc = Wildcard()
    assert isinstance(wc, Wildcard)


def test_create_meta_annotation():
    meta = MetaAnnotation(data={"pos": (100, 200), "label": "node1"})
    assert meta.data["pos"] == (100, 200)
    assert meta.data["label"] == "node1"
