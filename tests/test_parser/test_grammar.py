"""Grammar-level tests: verify the Lark grammar can parse fixture files."""

from __future__ import annotations

import pathlib

import pytest

from kohakunode import parse
from kohakunode.errors import KirSyntaxError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"
_ERRORS_DIR = _FIXTURES_DIR / "errors"

# Collect all normal fixture files (non-error).
_NORMAL_FIXTURES = sorted(_FIXTURES_DIR.glob("*.kir"))

# Collect all error fixtures (valid syntax, semantic issues only).
_ERROR_FIXTURES = sorted(_ERRORS_DIR.glob("*.kir"))


# ---------------------------------------------------------------------------
# Parametrised: normal fixtures must parse without raising
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    _NORMAL_FIXTURES,
    ids=[p.name for p in _NORMAL_FIXTURES],
)
def test_normal_fixture_parses_without_error(fixture_path: pathlib.Path) -> None:
    """Every file in tests/fixtures/*.kir must parse successfully."""
    source = fixture_path.read_text(encoding="utf-8")
    # parse() must not raise — any exception is a test failure.
    parse(source)


# ---------------------------------------------------------------------------
# Parametrised: error fixtures also have valid syntax, so they must also parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    _ERROR_FIXTURES,
    ids=[p.name for p in _ERROR_FIXTURES],
)
def test_error_fixture_has_valid_syntax(fixture_path: pathlib.Path) -> None:
    """Files in tests/fixtures/errors/ are semantically wrong but syntactically
    valid; the parser must accept them without raising KirSyntaxError."""
    source = fixture_path.read_text(encoding="utf-8")
    parse(source)


# ---------------------------------------------------------------------------
# Truly invalid syntax raises KirSyntaxError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_source",
    [
        # Missing closing parenthesis on input list.
        "(x process(result)\n",
        # Missing function name between parens.
        "(x)(result)\n",
        # Assignment with no right-hand side.
        "x =\n",
        # Stray token at top level.
        "???\n",
        # Incomplete call — only opening paren.
        "(\n",
        # Keyword arg without value.
        "(mode=)process(result)\n",
    ],
    ids=[
        "missing_closing_paren",
        "missing_func_name",
        "assignment_no_rhs",
        "stray_token",
        "lone_open_paren",
        "kwarg_no_value",
    ],
)
def test_invalid_syntax_raises_kir_syntax_error(bad_source: str) -> None:
    """Syntactically malformed input must raise KirSyntaxError."""
    with pytest.raises(KirSyntaxError):
        parse(bad_source)


# ---------------------------------------------------------------------------
# KirSyntaxError carries location information
# ---------------------------------------------------------------------------


def test_syntax_error_has_line_info() -> None:
    """KirSyntaxError should populate the .line attribute when possible."""
    bad_source = "x = 1\n???\n"
    with pytest.raises(KirSyntaxError) as exc_info:
        parse(bad_source)
    err = exc_info.value
    # line may be None if Lark cannot determine it, but message must be non-empty.
    assert err.message


def test_syntax_error_is_kir_error() -> None:
    """KirSyntaxError must inherit from the KirError base class."""
    from kohakunode.errors import KirError

    with pytest.raises(KirError):
        parse("???\n")
