"""Convenience wrapper for reading .kir files into a Program AST."""

from __future__ import annotations

from pathlib import Path

from kohakunode.ast.nodes import Program
from kohakunode.errors import KirSyntaxError
from kohakunode.parser.parser import parse


def read(path: str | Path) -> Program:
    """Read a .kir file and return the root Program AST node.

    Args:
        path: Path to the .kir file (str or pathlib.Path).

    Raises:
        KirSyntaxError: if the file is not found, cannot be read, or contains
            a syntax error.
    """
    try:
        source = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise KirSyntaxError(f"File not found: {path}") from exc
    except IOError as exc:
        raise KirSyntaxError(f"Could not read file: {path}: {exc}") from exc

    return parse(source)


def read_string(source: str) -> Program:
    """Parse a KIR source string and return the root Program AST node.

    Convenience function so callers can import everything from
    ``kohakunode.serializer`` without reaching into the parser package.

    Args:
        source: KIR source code as a string.

    Raises:
        KirSyntaxError: if the source contains a syntax error.
    """
    return parse(source)
