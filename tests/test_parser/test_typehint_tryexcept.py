"""Parser tests for @typehint blocks, typed assignments, and @try/@except."""

from kohakunode import parse
from kohakunode.ast.nodes import (
    Assignment,
    FuncCall,
    Literal,
    Program,
    TryExcept,
    TypeExpr,
    TypeHintBlock,
    TypeHintEntry,
)
from kohakunode.serializer.writer import Writer

# ---------------------------------------------------------------------------
# The canonical test string from the spec
# ---------------------------------------------------------------------------

_CANONICAL_SRC = """\
@typehint:
    (int, int)add(int)
    (str)to_int(int)

counter: int = 0
@try:
    (counter, 1)add(counter)
@except:
    (0)identity(counter)
"""


def test_canonical_parse_no_error() -> None:
    """The canonical test string must parse without raising."""
    prog = parse(_CANONICAL_SRC)
    assert isinstance(prog, Program)


# ---------------------------------------------------------------------------
# @typehint block
# ---------------------------------------------------------------------------


def test_typehint_entries_extracted_to_program() -> None:
    """TypeHintBlock entries are hoisted into Program.typehints."""
    prog = parse(_CANONICAL_SRC)
    assert prog.typehints is not None
    assert len(prog.typehints) == 2

    # TypeHintBlock should NOT appear in Program.body
    for stmt in prog.body:
        assert not isinstance(stmt, TypeHintBlock)


def test_typehint_entry_add() -> None:
    """(int, int)add(int) → correct TypeHintEntry."""
    prog = parse(_CANONICAL_SRC)
    entry = prog.typehints[0]

    assert isinstance(entry, TypeHintEntry)
    assert entry.func_name == "add"
    assert len(entry.input_types) == 2
    assert entry.input_types[0].name == "int"
    assert entry.input_types[0].is_optional is False
    assert entry.input_types[0].union_of is None
    assert entry.input_types[1].name == "int"
    assert len(entry.output_types) == 1
    assert entry.output_types[0].name == "int"


def test_typehint_entry_to_int() -> None:
    """(str)to_int(int) → correct TypeHintEntry."""
    prog = parse(_CANONICAL_SRC)
    entry = prog.typehints[1]

    assert isinstance(entry, TypeHintEntry)
    assert entry.func_name == "to_int"
    assert len(entry.input_types) == 1
    assert entry.input_types[0].name == "str"
    assert len(entry.output_types) == 1
    assert entry.output_types[0].name == "int"


def test_typehint_empty_inputs_outputs() -> None:
    """()no_args() is a valid typehint entry with empty in/out lists."""
    src = "@typehint:\n    ()no_args()\n"
    prog = parse(src)
    assert prog.typehints is not None
    entry = prog.typehints[0]
    assert entry.func_name == "no_args"
    assert entry.input_types == []
    assert entry.output_types == []


# ---------------------------------------------------------------------------
# Type expressions
# ---------------------------------------------------------------------------


def test_type_name_simple() -> None:
    """A plain NAME type like 'int' produces TypeExpr(name='int')."""
    src = "@typehint:\n    (int)f(str)\n"
    prog = parse(src)
    entry = prog.typehints[0]
    t_in = entry.input_types[0]
    assert isinstance(t_in, TypeExpr)
    assert t_in.name == "int"
    assert t_in.is_optional is False
    assert t_in.union_of is None


def test_type_optional() -> None:
    """'str?' produces TypeExpr(name='str', is_optional=True)."""
    src = "@typehint:\n    (str?)f(int)\n"
    prog = parse(src)
    t = prog.typehints[0].input_types[0]
    assert t.name == "str"
    assert t.is_optional is True
    assert t.union_of is None


def test_type_any_wildcard() -> None:
    """'_' produces TypeExpr(name='Any')."""
    src = "@typehint:\n    (_)f(_)\n"
    prog = parse(src)
    t_in = prog.typehints[0].input_types[0]
    t_out = prog.typehints[0].output_types[0]
    assert t_in.name == "Any"
    assert t_out.name == "Any"


def test_type_union() -> None:
    """'int | float' produces a TypeExpr with union_of=[int, float]."""
    src = "@typehint:\n    (int | float)f(int | str)\n"
    prog = parse(src)
    entry = prog.typehints[0]

    t_in = entry.input_types[0]
    assert t_in.union_of is not None
    assert len(t_in.union_of) == 2
    assert t_in.union_of[0].name == "int"
    assert t_in.union_of[1].name == "float"

    t_out = entry.output_types[0]
    assert t_out.union_of is not None
    assert t_out.union_of[0].name == "int"
    assert t_out.union_of[1].name == "str"


# ---------------------------------------------------------------------------
# Typed assignment
# ---------------------------------------------------------------------------


def test_typed_assignment_basic() -> None:
    """'counter: int = 0' produces Assignment with type_annotation."""
    prog = parse(_CANONICAL_SRC)
    stmt = prog.body[0]

    assert isinstance(stmt, Assignment)
    assert stmt.target == "counter"
    assert isinstance(stmt.value, Literal)
    assert stmt.value.value == 0
    assert stmt.type_annotation is not None
    assert stmt.type_annotation.name == "int"
    assert stmt.type_annotation.is_optional is False


def test_plain_assignment_has_no_type_annotation() -> None:
    """A plain 'x = 5' produces Assignment with type_annotation=None."""
    prog = parse("x = 5\n")
    stmt = prog.body[0]
    assert isinstance(stmt, Assignment)
    assert stmt.type_annotation is None


def test_typed_assignment_optional_type() -> None:
    """'result: tensor? = None' is valid; type_annotation.is_optional is True."""
    src = "result: tensor? = None\n"
    prog = parse(src)
    stmt = prog.body[0]
    assert isinstance(stmt, Assignment)
    assert stmt.type_annotation is not None
    assert stmt.type_annotation.name == "tensor"
    assert stmt.type_annotation.is_optional is True


# ---------------------------------------------------------------------------
# @try/@except
# ---------------------------------------------------------------------------


def test_try_except_structure() -> None:
    """@try/@except produces a TryExcept node in Program.body."""
    prog = parse(_CANONICAL_SRC)
    stmt = prog.body[1]
    assert isinstance(stmt, TryExcept)


def test_try_body() -> None:
    """The @try block contains (counter, 1)add(counter)."""
    prog = parse(_CANONICAL_SRC)
    te = prog.body[1]
    assert isinstance(te, TryExcept)
    assert len(te.try_body) == 1
    call = te.try_body[0]
    assert isinstance(call, FuncCall)
    assert call.func_name == "add"


def test_except_body() -> None:
    """The @except block contains (0)identity(counter)."""
    prog = parse(_CANONICAL_SRC)
    te = prog.body[1]
    assert isinstance(te, TryExcept)
    assert len(te.except_body) == 1
    call = te.except_body[0]
    assert isinstance(call, FuncCall)
    assert call.func_name == "identity"


def test_try_except_multiple_stmts() -> None:
    """Multiple statements inside @try and @except are all captured."""
    src = """\
@try:
    (a, b)add(c)
    (c)square(d)
@except:
    (a)identity(c)
    (b)identity(d)
"""
    prog = parse(src)
    te = prog.body[0]
    assert isinstance(te, TryExcept)
    assert len(te.try_body) == 2
    assert len(te.except_body) == 2
    assert te.try_body[0].func_name == "add"
    assert te.try_body[1].func_name == "square"
    assert te.except_body[0].func_name == "identity"
    assert te.except_body[1].func_name == "identity"


# ---------------------------------------------------------------------------
# Writer roundtrip
# ---------------------------------------------------------------------------


def test_writer_typehint_block() -> None:
    """Writer serializes Program.typehints back to @typehint: block."""
    prog = parse(_CANONICAL_SRC)
    out = Writer().write(prog)
    assert "@typehint:" in out
    assert "    (int, int)add(int)" in out
    assert "    (str)to_int(int)" in out


def test_writer_typed_assignment() -> None:
    """Writer emits 'name: type = value' for typed assignments."""
    prog = parse(_CANONICAL_SRC)
    out = Writer().write(prog)
    assert "counter: int = 0" in out


def test_writer_try_except() -> None:
    """Writer emits @try: / @except: blocks."""
    prog = parse(_CANONICAL_SRC)
    out = Writer().write(prog)
    assert "@try:" in out
    assert "    (counter, 1)add(counter)" in out
    assert "@except:" in out
    assert "    (0)identity(counter)" in out


def test_writer_roundtrip_stable() -> None:
    """Parsing the writer output produces the same AST structure."""
    prog1 = parse(_CANONICAL_SRC)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)
    out2 = Writer().write(prog2)
    assert out1 == out2
