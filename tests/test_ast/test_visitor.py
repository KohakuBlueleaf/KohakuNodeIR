"""Tests for kohakunode.ast.visitor — ASTVisitor and ASTTransformer."""


import pytest

from kohakunode.ast.nodes import (
    Assignment,
    FuncCall,
    Identifier,
    Literal,
    Namespace,
    Program,
    SubgraphDef,
    Parameter,
    Wildcard,
)
from kohakunode.ast.visitor import ASTTransformer, ASTVisitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_simple_program() -> Program:
    """Create a small Program with an Assignment and a FuncCall."""
    assign = Assignment(
        target="x",
        value=Literal(value=1, literal_type="int"),
        line=1,
    )
    call = FuncCall(
        inputs=[Identifier(name="x")],
        func_name="do_thing",
        outputs=["y"],
        line=2,
    )
    return Program(body=[assign, call])


def _make_nested_program() -> Program:
    """Program with a Namespace containing a FuncCall."""
    inner_call = FuncCall(
        inputs=[Identifier(name="a")],
        func_name="inner_fn",
        outputs=["b"],
        line=3,
    )
    ns = Namespace(name="my_ns", body=[inner_call], line=2)
    outer_call = FuncCall(
        inputs=[Identifier(name="c")],
        func_name="outer_fn",
        outputs=["d"],
        line=1,
    )
    return Program(body=[outer_call, ns])


# ---------------------------------------------------------------------------
# test_visitor_dispatch
# ---------------------------------------------------------------------------


class _CountingVisitor(ASTVisitor):
    """Counts how many FuncCall and Identifier nodes are visited."""

    def __init__(self):
        self.func_call_count = 0
        self.identifier_count = 0
        self.assignment_count = 0

    def visit_FuncCall(self, node: FuncCall) -> None:
        self.func_call_count += 1
        self.visit_children(node)

    def visit_Identifier(self, node: Identifier) -> None:
        self.identifier_count += 1

    def visit_Assignment(self, node: Assignment) -> None:
        self.assignment_count += 1
        self.visit_children(node)


def test_visitor_dispatch_counts_func_calls():
    prog = _make_simple_program()
    v = _CountingVisitor()
    v.visit(prog)
    assert v.func_call_count == 1


def test_visitor_dispatch_counts_assignments():
    prog = _make_simple_program()
    v = _CountingVisitor()
    v.visit(prog)
    assert v.assignment_count == 1


def test_visitor_dispatch_counts_identifiers():
    # The FuncCall input is an Identifier; the Assignment value is a Literal.
    prog = _make_simple_program()
    v = _CountingVisitor()
    v.visit(prog)
    assert v.identifier_count == 1


def test_visitor_dispatch_multiple_func_calls():
    call1 = FuncCall(inputs=[], func_name="a", outputs=[])
    call2 = FuncCall(inputs=[], func_name="b", outputs=[])
    call3 = FuncCall(inputs=[], func_name="c", outputs=[])
    prog = Program(body=[call1, call2, call3])
    v = _CountingVisitor()
    v.visit(prog)
    assert v.func_call_count == 3


def test_visitor_dispatch_generic_visit_is_noop():
    """generic_visit does nothing unless overridden."""
    prog = _make_simple_program()
    v = ASTVisitor()
    # Should not raise; default generic_visit is a no-op.
    v.generic_visit(prog)


# ---------------------------------------------------------------------------
# test_visitor_children
# ---------------------------------------------------------------------------


class _DepthVisitor(ASTVisitor):
    """Recursively visits all nodes and counts them by type name."""

    def __init__(self):
        self.visited: list[str] = []

    def generic_visit(self, node) -> None:
        self.visited.append(type(node).__name__)
        self.visit_children(node)

    def visit_Program(self, node: Program) -> None:
        self.visited.append("Program")
        self.visit_children(node)

    def visit_FuncCall(self, node: FuncCall) -> None:
        self.visited.append("FuncCall")
        self.visit_children(node)

    def visit_Namespace(self, node: Namespace) -> None:
        self.visited.append("Namespace")
        self.visit_children(node)

    def visit_Identifier(self, node: Identifier) -> None:
        self.visited.append("Identifier")

    def visit_Assignment(self, node: Assignment) -> None:
        self.visited.append("Assignment")
        self.visit_children(node)

    def visit_Literal(self, node: Literal) -> None:
        self.visited.append("Literal")


def test_visitor_children_recurse_into_namespace():
    prog = _make_nested_program()
    v = _DepthVisitor()
    v.visit(prog)
    assert "Namespace" in v.visited
    assert "FuncCall" in v.visited


def test_visitor_children_sees_identifiers_inside_func_call():
    prog = _make_nested_program()
    v = _DepthVisitor()
    v.visit(prog)
    # outer_fn input 'c' and inner_fn input 'a' should be visited.
    assert v.visited.count("Identifier") >= 2


def test_visitor_children_sees_program():
    prog = _make_simple_program()
    v = _DepthVisitor()
    v.visit(prog)
    assert "Program" in v.visited


def test_visitor_children_literal_visited():
    prog = _make_simple_program()
    v = _DepthVisitor()
    v.visit(prog)
    # The Assignment has a Literal as its value
    assert "Literal" in v.visited


def test_visitor_visit_children_empty_body():
    """visit_children on a node with no children should not raise."""
    v = ASTVisitor()
    v.visit_children(Identifier(name="x"))


# ---------------------------------------------------------------------------
# test_transformer_identity
# ---------------------------------------------------------------------------


def test_transformer_identity_returns_same_structure():
    """Default ASTTransformer should return a structurally unchanged tree."""
    prog = _make_simple_program()
    t = ASTTransformer()
    result = t.visit(prog)
    assert isinstance(result, Program)
    assert len(result.body) == 2
    assert isinstance(result.body[0], Assignment)
    assert isinstance(result.body[1], FuncCall)


def test_transformer_identity_preserves_func_name():
    prog = _make_simple_program()
    t = ASTTransformer()
    result = t.visit(prog)
    call = result.body[1]
    assert isinstance(call, FuncCall)
    assert call.func_name == "do_thing"


def test_transformer_identity_preserves_nested():
    prog = _make_nested_program()
    t = ASTTransformer()
    result = t.visit(prog)
    assert len(result.body) == 2
    ns = result.body[1]
    assert isinstance(ns, Namespace)
    assert ns.name == "my_ns"
    assert len(ns.body) == 1


def test_transformer_identity_preserves_assignment_target():
    prog = _make_simple_program()
    t = ASTTransformer()
    result = t.visit(prog)
    assign = result.body[0]
    assert isinstance(assign, Assignment)
    assert assign.target == "x"


# ---------------------------------------------------------------------------
# test_transformer_replace
# ---------------------------------------------------------------------------


class _IdentifierUpperTransformer(ASTTransformer):
    """Replaces every Identifier node with one whose name is uppercased."""

    def visit_Identifier(self, node: Identifier) -> Identifier:
        return Identifier(name=node.name.upper(), line=node.line)


def test_transformer_replace_identifier_names():
    prog = _make_simple_program()
    t = _IdentifierUpperTransformer()
    result = t.visit(prog)
    # The FuncCall's input Identifier("x") should become Identifier("X")
    call = result.body[1]
    assert isinstance(call, FuncCall)
    assert call.inputs[0].name == "X"


def test_transformer_replace_only_identifiers_not_assignments():
    prog = _make_simple_program()
    t = _IdentifierUpperTransformer()
    result = t.visit(prog)
    # Assignment target is a plain string, not an Identifier node — unchanged.
    assign = result.body[0]
    assert isinstance(assign, Assignment)
    assert assign.target == "x"


def test_transformer_replace_inside_namespace():
    prog = _make_nested_program()
    t = _IdentifierUpperTransformer()
    result = t.visit(prog)
    ns = result.body[1]
    assert isinstance(ns, Namespace)
    inner_call = ns.body[0]
    assert inner_call.inputs[0].name == "A"


def test_transformer_replace_does_not_alter_literals():
    prog = _make_simple_program()
    t = _IdentifierUpperTransformer()
    result = t.visit(prog)
    assign = result.body[0]
    # value is a Literal; transformer leaves it as-is
    assert isinstance(assign.value, Literal)
    assert assign.value.value == 1


class _FuncCallRemover(ASTTransformer):
    """Replaces FuncCall nodes with an Assignment to a sentinel literal."""

    def visit_FuncCall(self, node: FuncCall) -> Assignment:
        return Assignment(
            target="__removed__",
            value=Literal(value="removed", literal_type="str"),
        )


def test_transformer_replace_node_type():
    prog = _make_simple_program()
    t = _FuncCallRemover()
    result = t.visit(prog)
    # Second statement was a FuncCall; should now be an Assignment.
    assert isinstance(result.body[1], Assignment)
    assert result.body[1].target == "__removed__"
