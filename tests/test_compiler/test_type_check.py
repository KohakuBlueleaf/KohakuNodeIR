"""Type validation tests for TypeCheckPass.

Covers:
- Valid: all types match → no error
- Invalid: int port connected to str port → error
- Any matches everything
- Union: int | float matches int, float, rejects str
- Optional: tensor? matches tensor, matches None, rejects int
- Custom types match by exact name
- No @typehint → everything passes (all Any)
"""

import pytest

from kohakunode import parse
from kohakunode.ast.nodes import TypeExpr
from kohakunode.compiler.type_check import TypeCheckError, TypeCheckPass, _types_compatible


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check(source: str) -> None:
    """Parse *source* and run TypeCheckPass — raises TypeCheckError on failure."""
    prog = parse(source)
    TypeCheckPass().transform(prog)


def _make_type(name: str, optional: bool = False, union_of=None) -> TypeExpr:
    return TypeExpr(name=name, is_optional=optional, union_of=union_of)


# ---------------------------------------------------------------------------
# _types_compatible unit tests
# ---------------------------------------------------------------------------


class TestTypesCompatible:
    def test_any_expected_accepts_all(self) -> None:
        any_t = _make_type("Any")
        for name in ("int", "str", "float", "tensor", "my_custom"):
            assert _types_compatible(_make_type(name), any_t)

    def test_any_actual_matches_all(self) -> None:
        any_t = _make_type("Any")
        for expected_name in ("int", "str", "float"):
            assert _types_compatible(any_t, _make_type(expected_name))

    def test_exact_name_match(self) -> None:
        assert _types_compatible(_make_type("int"), _make_type("int"))
        assert _types_compatible(_make_type("str"), _make_type("str"))
        assert _types_compatible(_make_type("float"), _make_type("float"))
        assert _types_compatible(_make_type("tensor"), _make_type("tensor"))

    def test_exact_name_mismatch(self) -> None:
        assert not _types_compatible(_make_type("int"), _make_type("str"))
        assert not _types_compatible(_make_type("str"), _make_type("int"))
        assert not _types_compatible(_make_type("float"), _make_type("tensor"))

    # -- Union expected --

    def test_union_expected_int_matches_int(self) -> None:
        union = _make_type("Any", union_of=[_make_type("int"), _make_type("float")])
        assert _types_compatible(_make_type("int"), union)

    def test_union_expected_float_matches_float(self) -> None:
        union = _make_type("Any", union_of=[_make_type("int"), _make_type("float")])
        assert _types_compatible(_make_type("float"), union)

    def test_union_expected_rejects_str(self) -> None:
        union = _make_type("Any", union_of=[_make_type("int"), _make_type("float")])
        assert not _types_compatible(_make_type("str"), union)

    def test_union_expected_three_members(self) -> None:
        union = _make_type(
            "Any",
            union_of=[_make_type("int"), _make_type("float"), _make_type("str")],
        )
        assert _types_compatible(_make_type("int"), union)
        assert _types_compatible(_make_type("float"), union)
        assert _types_compatible(_make_type("str"), union)
        assert not _types_compatible(_make_type("bool"), union)

    # -- Optional expected --

    def test_optional_expected_matches_base_type(self) -> None:
        opt = _make_type("tensor", optional=True)
        assert _types_compatible(_make_type("tensor"), opt)

    def test_optional_expected_matches_none(self) -> None:
        opt = _make_type("str", optional=True)
        assert _types_compatible(_make_type("none"), opt)

    def test_optional_expected_rejects_other_type(self) -> None:
        opt = _make_type("tensor", optional=True)
        assert not _types_compatible(_make_type("int"), opt)

    def test_optional_expected_rejects_wrong_base(self) -> None:
        opt = _make_type("tensor", optional=True)
        assert not _types_compatible(_make_type("str"), opt)

    # -- Custom types --

    def test_custom_types_match_exact_name(self) -> None:
        assert _types_compatible(_make_type("my_tensor"), _make_type("my_tensor"))

    def test_custom_types_reject_different_names(self) -> None:
        assert not _types_compatible(_make_type("my_tensor"), _make_type("other_tensor"))

    # -- Any in actual position --

    def test_any_actual_with_optional_expected(self) -> None:
        opt = _make_type("tensor", optional=True)
        assert _types_compatible(_make_type("Any"), opt)


# ---------------------------------------------------------------------------
# TypeCheckPass integration tests — no error cases
# ---------------------------------------------------------------------------


class TestTypeCheckNoError:
    def test_no_typehint_everything_passes(self) -> None:
        """Without @typehint, all calls pass (default Any)."""
        src = "x = 10\ny = 20\n(x, y)add(result)\n"
        _check(src)  # Must not raise

    def test_valid_int_types_match(self) -> None:
        src = """\
@typehint:
    (int, int)add(int)

x: int = 5
y: int = 3
(x, y)add(result)
"""
        _check(src)  # Must not raise

    def test_valid_str_types_match(self) -> None:
        src = """\
@typehint:
    (str)print(_)

msg: str = "hello"
(msg)print()
"""
        _check(src)  # Must not raise

    def test_valid_any_matches_int(self) -> None:
        src = """\
@typehint:
    (Any)process(Any)

x: int = 42
(x)process(result)
"""
        _check(src)  # Must not raise

    def test_valid_any_matches_str(self) -> None:
        src = """\
@typehint:
    (Any)log(_)

msg: str = "hello"
(msg)log()
"""
        _check(src)  # Must not raise

    def test_valid_union_int_input(self) -> None:
        src = """\
@typehint:
    (int | float)normalize(float)

x: int = 5
(x)normalize(result)
"""
        _check(src)  # Must not raise

    def test_valid_union_float_input(self) -> None:
        src = """\
@typehint:
    (int | float)normalize(float)

x: float = 3.14
(x)normalize(result)
"""
        _check(src)  # Must not raise

    def test_valid_optional_base_type(self) -> None:
        src = """\
@typehint:
    (tensor?)process(tensor)

t: tensor = None
(t)process(result)
"""
        _check(src)  # Must not raise

    def test_valid_optional_none_input(self) -> None:
        src = """\
@typehint:
    (str?)lookup(str)

val: none = None
(val)lookup(result)
"""
        _check(src)  # Must not raise

    def test_valid_custom_type_match(self) -> None:
        src = """\
@typehint:
    (my_tensor)process(my_result)

t: my_tensor = None
(t)process(out)
"""
        _check(src)  # Must not raise

    def test_valid_literal_int_matches_int_hint(self) -> None:
        src = """\
@typehint:
    (int, int)add(int)

(5, 3)add(result)
"""
        _check(src)  # Must not raise

    def test_valid_literal_str_matches_str_hint(self) -> None:
        src = """\
@typehint:
    (str)print(_)

("hello")print()
"""
        _check(src)  # Must not raise

    def test_output_types_propagate_for_chained_calls(self) -> None:
        """Output type of one call becomes input type of next; valid chain."""
        src = """\
@typehint:
    (int, int)add(int)
    (int)to_string(str)

x: int = 3
y: int = 4
(x, y)add(total)
(total)to_string(text)
"""
        _check(src)  # Must not raise

    def test_untyped_variable_is_not_checked(self) -> None:
        """Variable without type annotation → inferred as Any → passes."""
        src = """\
@typehint:
    (str)print(_)

x = "hello"
(x)print()
"""
        _check(src)  # Must not raise


# ---------------------------------------------------------------------------
# TypeCheckPass integration tests — error cases
# ---------------------------------------------------------------------------


class TestTypeCheckError:
    def test_int_port_connected_to_str_port_raises(self) -> None:
        src = """\
@typehint:
    (str)print(_)

x: int = 42
(x)print()
"""
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        assert "print" in str(exc_info.value)

    def test_str_port_connected_to_int_port_raises(self) -> None:
        src = """\
@typehint:
    (int, int)add(int)

x: str = "hello"
y: int = 5
(x, y)add(result)
"""
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        assert "add" in str(exc_info.value)

    def test_union_rejects_non_member_type(self) -> None:
        """int | float hint rejects str argument."""
        src = """\
@typehint:
    (int | float)normalize(float)

x: str = "hello"
(x)normalize(result)
"""
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        assert "normalize" in str(exc_info.value)

    def test_optional_rejects_wrong_base(self) -> None:
        """tensor? hint rejects int argument."""
        src = """\
@typehint:
    (tensor?)process(tensor)

x: int = 5
(x)process(result)
"""
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        assert "process" in str(exc_info.value)

    def test_custom_type_rejects_wrong_name(self) -> None:
        src = """\
@typehint:
    (my_tensor)process(my_result)

t: int = 5
(t)process(out)
"""
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        assert "process" in str(exc_info.value)

    def test_error_message_contains_function_name(self) -> None:
        src = """\
@typehint:
    (str)my_func(_)

x: int = 1
(x)my_func()
"""
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        assert "my_func" in str(exc_info.value)

    def test_multiple_errors_all_reported(self) -> None:
        """TypeCheckError collects all errors (not just the first)."""
        src = """\
@typehint:
    (int)f(str)
    (str)g(_)

x: str = "hello"
y: int = 5
(x)f(out1)
(y)g()
"""
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        err = exc_info.value
        # Both f and g are mismatched
        assert len(err.errors) >= 2

    def test_chained_type_mismatch_propagates(self) -> None:
        """Type error in output propagates to next call if types don't match."""
        src = """\
@typehint:
    (int, int)add(int)
    (str)print(_)

x: str = "hello"
y: str = "world"
(x, y)add(total)
"""
        # add expects (int, int) but gets (str, str)
        with pytest.raises(TypeCheckError) as exc_info:
            _check(src)
        assert "add" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TypeCheckPass — no @typehint means Any everywhere
# ---------------------------------------------------------------------------


def test_no_typehint_passes_any_combination() -> None:
    """Without @typehint, any call with any argument types passes."""
    src = """\
x: str = "hello"
y: int = 42
(x, y)some_func(out)
(out)another(final)
"""
    _check(src)  # Must not raise


def test_typehint_for_one_func_does_not_affect_others() -> None:
    """Having @typehint for func A does not type-check func B."""
    src = """\
@typehint:
    (int)f(str)

x: int = 5
(x)f(out)

y: str = "hello"
(y, 42)untyped_func(result)
"""
    _check(src)  # Must not raise — untyped_func has no hint, so Any


# ---------------------------------------------------------------------------
# TypeCheckPass — pass is a no-op (returns same program)
# ---------------------------------------------------------------------------


def test_pass_returns_program_unchanged() -> None:
    """TypeCheckPass returns the program (same body) when no errors."""
    src = "@typehint:\n    (int)f(str)\n\nx: int = 5\n(x)f(out)\n"
    prog = parse(src)
    result = TypeCheckPass().transform(prog)
    assert result is prog or result.body == prog.body
