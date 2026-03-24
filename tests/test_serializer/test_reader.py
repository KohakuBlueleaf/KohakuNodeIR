"""Tests for kohakunode.serializer.reader — read() and read_string()."""


import pathlib
import tempfile

import pytest

from kohakunode.ast.nodes import Assignment, FuncCall, Namespace, Program
from kohakunode.errors import KirSyntaxError
from kohakunode.serializer.reader import read, read_string


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# test_read_string
# ---------------------------------------------------------------------------


def test_read_string_returns_program():
    source = "x = 42\n"
    result = read_string(source)
    assert isinstance(result, Program)


def test_read_string_simple_assignment():
    source = "x = 42\n"
    prog = read_string(source)
    assert len(prog.body) == 1
    stmt = prog.body[0]
    assert isinstance(stmt, Assignment)
    assert stmt.target == "x"
    assert stmt.value.value == 42


def test_read_string_func_call():
    source = "(a, b)process(result)\n"
    prog = read_string(source)
    assert len(prog.body) == 1
    stmt = prog.body[0]
    assert isinstance(stmt, FuncCall)
    assert stmt.func_name == "process"
    assert stmt.outputs == ["result"]


def test_read_string_namespace():
    source = "my_label:\n    ()fn(x)\n"
    prog = read_string(source)
    assert len(prog.body) == 1
    ns = prog.body[0]
    assert isinstance(ns, Namespace)
    assert ns.name == "my_label"


def test_read_string_multiple_statements():
    source = "x = 1\ny = 2\n(x, y)add(z)\n"
    prog = read_string(source)
    assert len(prog.body) == 3


def test_read_string_dataflow_mode():
    source = "@mode dataflow\n\n()load(x)\n"
    prog = read_string(source)
    assert prog.mode == "dataflow"


def test_read_string_invalid_syntax_raises():
    with pytest.raises(KirSyntaxError):
        read_string("??? bad syntax\n")


def test_read_string_empty_program():
    prog = read_string("")
    assert isinstance(prog, Program)
    assert prog.body == []


# ---------------------------------------------------------------------------
# test_read_file
# ---------------------------------------------------------------------------


def test_read_file_basic_assignment():
    path = _FIXTURES_DIR / "basic_assignment.kir"
    prog = read(path)
    assert isinstance(prog, Program)
    assert len(prog.body) >= 1


def test_read_file_assigns_correct_values():
    path = _FIXTURES_DIR / "basic_assignment.kir"
    prog = read(path)
    # First statement should be x = 42
    first = prog.body[0]
    assert isinstance(first, Assignment)
    assert first.target == "x"
    assert first.value.value == 42


def test_read_file_func_call_fixture():
    path = _FIXTURES_DIR / "func_call.kir"
    prog = read(path)
    assert isinstance(prog, Program)
    # At least one FuncCall in the body
    assert any(isinstance(s, FuncCall) for s in prog.body)


def test_read_file_branch_fixture():
    path = _FIXTURES_DIR / "branch.kir"
    prog = read(path)
    assert isinstance(prog, Program)
    assert len(prog.body) >= 2


def test_read_file_accepts_string_path():
    path = str(_FIXTURES_DIR / "basic_assignment.kir")
    prog = read(path)
    assert isinstance(prog, Program)


def test_read_file_accepts_pathlib_path():
    path = _FIXTURES_DIR / "basic_assignment.kir"
    assert isinstance(path, pathlib.Path)
    prog = read(path)
    assert isinstance(prog, Program)


def test_read_file_dataflow_fixture():
    path = _FIXTURES_DIR / "dataflow.kir"
    prog = read(path)
    assert prog.mode == "dataflow"


# ---------------------------------------------------------------------------
# test_read_missing_file
# ---------------------------------------------------------------------------


def test_read_missing_file_raises_kir_syntax_error():
    with pytest.raises(KirSyntaxError):
        read("/nonexistent/path/to/missing_file.kir")


def test_read_missing_file_error_message_contains_path():
    fake_path = "/nonexistent/path/missing.kir"
    with pytest.raises(KirSyntaxError) as exc_info:
        read(fake_path)
    assert "missing.kir" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


def test_read_missing_file_is_kir_error():
    from kohakunode.errors import KirError

    with pytest.raises(KirError):
        read("/definitely/does/not/exist.kir")


def test_read_file_with_temp_file():
    """read() can parse a valid KIR file written to a temporary file."""
    source = "x = 99\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".kir", delete=False, encoding="utf-8"
    ) as f:
        f.write(source)
        tmp_path = f.name
    prog = read(tmp_path)
    assert isinstance(prog, Program)
    assert len(prog.body) == 1
    assert prog.body[0].target == "x"
    assert prog.body[0].value.value == 99
