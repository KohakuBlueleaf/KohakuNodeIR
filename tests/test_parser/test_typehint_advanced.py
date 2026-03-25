"""Advanced @typehint parsing tests.

Covers union types, optional types, Any/wildcard, custom types,
multiple entries, and parse → write → re-parse roundtrip stability.
"""

from kohakunode import parse
from kohakunode.ast.nodes import Program, TypeExpr, TypeHintEntry
from kohakunode.serializer.writer import Writer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_typehint(src: str) -> list[TypeHintEntry]:
    """Parse a snippet and return Program.typehints."""
    prog = parse(src)
    assert prog.typehints is not None, "Expected typehints in program"
    return prog.typehints


# ---------------------------------------------------------------------------
# Union types
# ---------------------------------------------------------------------------


def test_union_type_int_float() -> None:
    """(int | float)add(float) — input union type parsed correctly."""
    entries = _parse_typehint("@typehint:\n    (int | float)add(float)\n")
    entry = entries[0]
    assert entry.func_name == "add"
    t_in = entry.input_types[0]
    assert t_in.union_of is not None
    assert len(t_in.union_of) == 2
    assert t_in.union_of[0].name == "int"
    assert t_in.union_of[1].name == "float"
    t_out = entry.output_types[0]
    assert t_out.name == "float"
    assert t_out.union_of is None


def test_union_type_three_members() -> None:
    """int | float | str union — all three members captured."""
    entries = _parse_typehint("@typehint:\n    (int | float | str)convert(str)\n")
    t_in = entries[0].input_types[0]
    assert t_in.union_of is not None
    assert len(t_in.union_of) == 3
    names = [m.name for m in t_in.union_of]
    assert names == ["int", "float", "str"]


def test_union_type_in_output() -> None:
    """Union type in output position: (str)convert(int | str) — output union captured."""
    entries = _parse_typehint("@typehint:\n    (str)convert(int | str)\n")
    t_out = entries[0].output_types[0]
    assert t_out.union_of is not None
    assert {m.name for m in t_out.union_of} == {"int", "str"}


def test_union_type_not_optional() -> None:
    """Union types do not set is_optional."""
    entries = _parse_typehint("@typehint:\n    (int | float)f(str)\n")
    t_in = entries[0].input_types[0]
    assert t_in.is_optional is False


# ---------------------------------------------------------------------------
# Optional types
# ---------------------------------------------------------------------------


def test_optional_input_type() -> None:
    """(tensor?)normalize(tensor) — optional input type parsed."""
    entries = _parse_typehint("@typehint:\n    (tensor?)normalize(tensor)\n")
    entry = entries[0]
    assert entry.func_name == "normalize"
    t_in = entry.input_types[0]
    assert isinstance(t_in, TypeExpr)
    assert t_in.name == "tensor"
    assert t_in.is_optional is True
    assert t_in.union_of is None
    t_out = entry.output_types[0]
    assert t_out.name == "tensor"
    assert t_out.is_optional is False


def test_optional_output_type() -> None:
    """(str)lookup(str?) — optional output type parsed."""
    entries = _parse_typehint("@typehint:\n    (str)lookup(str?)\n")
    t_out = entries[0].output_types[0]
    assert t_out.name == "str"
    assert t_out.is_optional is True


def test_optional_multiple_inputs() -> None:
    """(int, float?)safe_div(float) — mix of plain and optional inputs."""
    entries = _parse_typehint("@typehint:\n    (int, float?)safe_div(float)\n")
    t0 = entries[0].input_types[0]
    t1 = entries[0].input_types[1]
    assert t0.name == "int"
    assert t0.is_optional is False
    assert t1.name == "float"
    assert t1.is_optional is True


# ---------------------------------------------------------------------------
# Any / wildcard
# ---------------------------------------------------------------------------


def test_any_wildcard_input() -> None:
    """(Any, _)concat(str) — both Any and _ treated as Any."""
    entries = _parse_typehint("@typehint:\n    (Any, _)concat(str)\n")
    entry = entries[0]
    assert entry.func_name == "concat"
    assert len(entry.input_types) == 2
    assert entry.input_types[0].name == "Any"
    assert entry.input_types[0].union_of is None
    assert entry.input_types[0].is_optional is False
    assert entry.input_types[1].name == "Any"


def test_any_explicit_keyword() -> None:
    """(Any)f(Any) — explicit Any keyword."""
    entries = _parse_typehint("@typehint:\n    (Any)f(Any)\n")
    assert entries[0].input_types[0].name == "Any"
    assert entries[0].output_types[0].name == "Any"


def test_wildcard_only_output() -> None:
    """(str)print(_) — wildcard/Any output (side-effect function)."""
    entries = _parse_typehint("@typehint:\n    (str)print(_)\n")
    t_out = entries[0].output_types[0]
    assert t_out.name == "Any"


# ---------------------------------------------------------------------------
# Custom types
# ---------------------------------------------------------------------------


def test_custom_type_input() -> None:
    """(my_tensor)process(my_result) — custom type names preserved verbatim."""
    entries = _parse_typehint("@typehint:\n    (my_tensor)process(my_result)\n")
    entry = entries[0]
    assert entry.func_name == "process"
    assert entry.input_types[0].name == "my_tensor"
    assert entry.output_types[0].name == "my_result"
    assert entry.input_types[0].is_optional is False
    assert entry.input_types[0].union_of is None


def test_custom_type_optional() -> None:
    """(my_tensor?)process(my_result) — custom optional type."""
    entries = _parse_typehint("@typehint:\n    (my_tensor?)process(my_result)\n")
    t_in = entries[0].input_types[0]
    assert t_in.name == "my_tensor"
    assert t_in.is_optional is True


def test_custom_type_in_union() -> None:
    """(my_type | int)f(str) — custom type inside a union."""
    entries = _parse_typehint("@typehint:\n    (my_type | int)f(str)\n")
    t_in = entries[0].input_types[0]
    assert t_in.union_of is not None
    names = {m.name for m in t_in.union_of}
    assert "my_type" in names
    assert "int" in names


# ---------------------------------------------------------------------------
# Multiple entries
# ---------------------------------------------------------------------------


def test_multiple_entries_count() -> None:
    """Multiple typehint lines all parsed."""
    src = """\
@typehint:
    (int, int)add(int)
    (int, int)multiply(int)
    (int)to_string(str)
    (str)print(_)
"""
    entries = _parse_typehint(src)
    assert len(entries) == 4


def test_multiple_entries_names() -> None:
    """Each typehint entry has the correct func_name."""
    src = """\
@typehint:
    (int, int)add(int)
    (int, int)multiply(int)
    (int)to_string(str)
    (str)print(_)
"""
    entries = _parse_typehint(src)
    names = [e.func_name for e in entries]
    assert names == ["add", "multiply", "to_string", "print"]


def test_multiple_entries_type_correctness() -> None:
    """Spot-check types in a multi-entry block."""
    src = """\
@typehint:
    (int, int)add(int)
    (float?)safe_sqrt(float)
    (Any, str)log(_)
"""
    entries = _parse_typehint(src)
    # add: (int, int) -> int
    assert entries[0].input_types[0].name == "int"
    assert entries[0].output_types[0].name == "int"
    # safe_sqrt: (float?) -> float
    assert entries[1].input_types[0].is_optional is True
    assert entries[1].output_types[0].name == "float"
    # log: (Any, str) -> _
    assert entries[2].input_types[0].name == "Any"
    assert entries[2].output_types[0].name == "Any"


def test_multiple_typehint_blocks_merged() -> None:
    """Two @typehint: blocks in the same program are merged into one list."""
    src = """\
@typehint:
    (int)f(str)

@typehint:
    (str)g(int)
"""
    prog = parse(src)
    assert prog.typehints is not None
    assert len(prog.typehints) == 2
    assert prog.typehints[0].func_name == "f"
    assert prog.typehints[1].func_name == "g"


def test_typehint_block_not_in_body() -> None:
    """@typehint entries are hoisted out of Program.body."""
    src = "@typehint:\n    (int)f(str)\nx = 1\n"
    prog = parse(src)
    from kohakunode.ast.nodes import TypeHintBlock

    for stmt in prog.body:
        assert not isinstance(stmt, TypeHintBlock)


# ---------------------------------------------------------------------------
# Roundtrip: parse → write → re-parse → compare
# ---------------------------------------------------------------------------


def test_roundtrip_simple_typehint() -> None:
    """Simple typehint roundtrip is stable after one write."""
    src = "@typehint:\n    (int, int)add(int)\n    (str)print(_)\n"
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)
    out2 = Writer().write(prog2)
    assert out1 == out2


def test_roundtrip_union_typehint() -> None:
    """Union type roundtrip is stable."""
    src = "@typehint:\n    (int | float)f(str)\n"
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)
    out2 = Writer().write(prog2)
    assert out1 == out2


def test_roundtrip_optional_typehint() -> None:
    """Optional type roundtrip is stable."""
    src = "@typehint:\n    (tensor?)normalize(tensor)\n"
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)
    out2 = Writer().write(prog2)
    assert out1 == out2


def test_roundtrip_custom_type() -> None:
    """Custom type name roundtrip is stable."""
    src = "@typehint:\n    (my_tensor)process(my_result)\n"
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)
    out2 = Writer().write(prog2)
    assert out1 == out2


def test_roundtrip_preserves_entry_count() -> None:
    """Entry count is preserved through roundtrip."""
    src = """\
@typehint:
    (int, int)add(int)
    (int, int)multiply(int)
    (int)to_string(str)
    (str)print(_)
"""
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)
    assert prog2.typehints is not None
    assert len(prog2.typehints) == 4


def test_roundtrip_with_body_statements() -> None:
    """Full program with typehint block and body roundtrips stably."""
    src = """\
@typehint:
    (int, int)add(int)
    (int)to_string(str)

x: int = 10
y: int = 20
(x, y)add(sum)
(sum)to_string(text)
"""
    prog1 = parse(src)
    out1 = Writer().write(prog1)
    prog2 = parse(out1)
    out2 = Writer().write(prog2)
    assert out1 == out2
