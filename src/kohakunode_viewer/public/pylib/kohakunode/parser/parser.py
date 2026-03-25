"""Public parse API for KohakuNodeIR.

Entry points:
    parse(source)     -- parse a KIR source string, return a Program AST node.
    parse_file(path)  -- convenience wrapper that reads a file then calls parse().
"""

import pathlib

import lark
import lark.exceptions
import lark.indenter

from kohakunode.ast.nodes import Program
from kohakunode.errors import KirSyntaxError
from kohakunode.parser.transformer import KirTransformer

# ---------------------------------------------------------------------------
# Indenter
# ---------------------------------------------------------------------------

_GRAMMAR_PATH = pathlib.Path(__file__).parent.parent / "grammar" / "kir.lark"


class KirIndenter(lark.indenter.Indenter):
    """Postlex indenter configured for the KIR grammar."""

    NL_type = "_NEWLINE"
    OPEN_PAREN_types = ["LPAR", "LSQB", "LBRACE"]
    CLOSE_PAREN_types = ["RPAR", "RSQB", "RBRACE"]
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 4


# ---------------------------------------------------------------------------
# Lazy parser singleton
# ---------------------------------------------------------------------------

_parser: lark.Lark | None = None


def _get_parser() -> lark.Lark:
    """Return the module-level Lark parser, creating it on first call."""
    global _parser
    if _parser is None:
        grammar_text = _GRAMMAR_PATH.read_text(encoding="utf-8")
        _parser = lark.Lark(
            grammar_text,
            parser="lalr",
            lexer="contextual",
            postlex=KirIndenter(),
            propagate_positions=True,
        )
    return _parser


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(source: str) -> Program:
    """Parse a KIR source string and return the root Program AST node.

    Raises:
        KirSyntaxError: if the source contains a syntax error.
    """
    # Ensure source ends with a newline — the grammar requires newline-terminated
    # statements, so a missing trailing newline would cause a parse error.
    if source and not source.endswith("\n"):
        source += "\n"

    try:
        tree = _get_parser().parse(source)
    except lark.exceptions.LarkError as exc:
        # Try to extract line / column information from the exception.
        line: int | None = None
        column: int | None = None
        source_line: str | None = None

        if isinstance(exc, lark.exceptions.UnexpectedInput):
            line = getattr(exc, "line", None)
            column = getattr(exc, "column", None)
            if line is not None:
                src_lines = source.splitlines()
                idx = line - 1
                if 0 <= idx < len(src_lines):
                    source_line = src_lines[idx]

        raise KirSyntaxError(
            str(exc),
            line=line,
            column=column,
            source_line=source_line,
        ) from exc

    return KirTransformer().transform(tree)


def parse_file(path: str | pathlib.Path) -> Program:
    """Read a KIR source file and return the root Program AST node.

    Args:
        path: Path to the .kir file (str or pathlib.Path).

    Raises:
        KirSyntaxError: if the file contains a syntax error.
        OSError: if the file cannot be read.
    """
    source = pathlib.Path(path).read_text(encoding="utf-8")
    return parse(source)
