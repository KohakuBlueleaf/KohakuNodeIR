"""Editor queries over KIR text, independent of any protocol.

Positions are 0-based (line, character), as in LSP. Diagnostics and
formatting come from one of two cores: "python" (the reference) or "rust"
(``kohakunode._rs``, byte-identical on the golden corpus). Hover, completion
and go-to-definition read the program structure from the Python parser.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from kohakunode import _rs
except ImportError:  # a source tree without the built extension
    _rs = None

from kohakunode.check import check
from kohakunode.errors import KirSignatureError, KirSyntaxError
from kohakunode.sig.env import NodeEnv, Resolved, build_env
from kohakunode.sig.model import Signature
from kohakunode.sig.std import STD
from kohakunode.sig.types import type_text
from kohakunode.syntax.ast import BUILTINS, Def, Namespace, Program, walk
from kohakunode.syntax.parser import parse
from kohakunode.syntax.writer import write

DIRECTIVES = ["use", "def", "meta", "hint", "dataflow", "try", "except", "typehint", "mode"]
CORES = ("python", "rust")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
# Both cores end a positioned syntax error message with this (errors.py).
_WHERE = re.compile(r"\(line (\d+), column (\d+)\)$")


def default_core() -> str:
    return "rust" if _rs is not None else "python"


def _core(core: str | None) -> str:
    core = core or default_core()
    if core not in CORES:
        raise ValueError(f"unknown core {core!r}; known: {list(CORES)}")
    if core == "rust" and _rs is None:
        raise ValueError("core 'rust' needs the kohakunode._rs extension (build with maturin)")
    return core


@dataclass
class Problem:
    line: int  # 0-based
    start: int
    end: int
    severity: str  # "error" | "warning"
    code: str
    message: str


@dataclass
class Analysis:
    program: Program | None
    env: NodeEnv | None
    problems: list[Problem]


def analyze(
    text: str, path: str | None = None, sig_path: list[str] = (), core: str | None = None
) -> Analysis:
    core = _core(core)
    lines = text.splitlines() or [""]

    def whole(line_1: int | None) -> tuple[int, int, int]:
        n = max(0, min((line_1 or 1) - 1, len(lines) - 1))
        body = lines[n]
        return n, len(body) - len(body.lstrip()), len(body)

    def syntax(message: str, line: int | None, column: int | None) -> Problem:
        n, _, end = whole(line)
        col = max(0, (column or 1) - 1)
        return Problem(n, col, max(end, col + 1), "error", "E001", message)

    def found(code: str, severity: str, message: str, line: int | None) -> Problem:
        n, start, end = whole(line)
        return Problem(n, start, end, severity, code, message)

    base = Path(path).parent if path else None
    # Program structure (hover, completion, definition) always comes from the
    # Python parser; the core decides the diagnostics.
    program, env = None, None
    try:
        program = parse(text)
        env = build_env(program, None, base, [Path(p) for p in sig_path])
    except (KirSyntaxError, KirSignatureError) as exc:
        python_error = exc
    else:
        python_error = None

    if core == "rust":
        try:
            found_json = _rs.check(
                text, [], base=str(base) if base else None, sig_path=list(sig_path)
            )
        except _rs.KirSyntaxError as exc:
            message = str(exc)
            where = _WHERE.search(message)
            line, column = (int(where[1]), int(where[2])) if where else (None, None)
            return Analysis(None, None, [syntax(message, line, column)])
        problems = [
            found(d["code"], d["severity"], d["message"], d["line"]) for d in json.loads(found_json)
        ]
        return Analysis(program, env, problems)

    if isinstance(python_error, KirSyntaxError):
        exc = python_error
        return Analysis(None, None, [syntax(str(exc), exc.line, exc.column)])
    if isinstance(python_error, KirSignatureError):
        return Analysis(program, None, [found("E002", "error", str(python_error), None)])
    problems = [found(d.code, d.severity, d.message, d.line) for d in check(program, env)]
    return Analysis(program, env, problems)


def word_at(text: str, line: int, character: int) -> tuple[str, int, int] | None:
    lines = text.splitlines()
    if line >= len(lines):
        return None
    for m in _WORD.finditer(lines[line]):
        if m.start() <= character <= m.end():
            return m.group(), m.start(), m.end()
    return None


def signature_markdown(sig: Signature, library: str | None) -> str:
    ins = []
    for p in sig.inputs:
        text = f"{p.name}: {type_text(p.type)}"
        if not p.required:
            text += f" = {p.default!r}"
        ins.append(text)
    outs = ", ".join(f"{p.name}: {type_text(p.type)}" for p in sig.outputs)
    head = f"({', '.join(ins)}){sig.name}({outs})"
    flags = []
    if sig.mutates:
        flags.append(f"mutates {', '.join(sig.mutates)}")
    if sig.ordered:
        flags.append("ordered")
    parts = [f"```kir\n{head}\n```"]
    if library:
        parts.append(f"library `{library}`" + (f" · {' · '.join(flags)}" if flags else ""))
    if sig.doc:
        parts.append(sig.doc)
    return "\n\n".join(parts)


def hover(a: Analysis, text: str, line: int, character: int) -> str | None:
    w = word_at(text, line, character)
    if w is None or a.env is None:
        return None
    word = w[0]
    if word in BUILTINS:
        return f"builtin `{word}`"
    r = a.env.resolve(word)
    if isinstance(r, Resolved):
        lib = r.library.name if r.library else ("@def" if r.definition else "@typehint")
        return signature_markdown(r.signature, lib)
    if a.program is not None:
        for s in walk(a.program.body):
            if isinstance(s, Namespace) and s.label == word:
                return f"namespace `{word}` (line {s.line})"
    return None


def completions(a: Analysis | None, text: str, line: int, character: int) -> list[tuple[str, str]]:
    """``(label, kind)`` pairs; kind is "node", "builtin", "label", "directive" or "def"."""
    current = text.splitlines()[line] if line < len(text.splitlines()) else ""
    before = current[:character]
    if before.rstrip().endswith("@") or re.search(r"@\w*$", before):
        return [(d, "directive") for d in DIRECTIVES]
    if before.count("`") % 2 == 1:
        labels = []
        if a is not None and a.program is not None:
            labels = sorted({s.label for s in walk(a.program.body) if isinstance(s, Namespace)})
        return [(x, "label") for x in labels]
    out = [(b, "builtin") for b in sorted(BUILTINS)]
    names = set(STD.signatures)
    if a is not None and a.env is not None:
        for lib, alias in a.env.libraries:
            names |= {f"{alias}.{n}" if alias else n for n in lib.signatures}
        out += [(d, "def") for d in sorted(a.env.defs)]
        names |= set(a.env.typehints)
    out += [(n, "node") for n in sorted(names)]
    return out


def definition(a: Analysis, text: str, line: int, character: int) -> int | None:
    """The 0-based line that defines the label or `@def` under the cursor."""
    w = word_at(text, line, character)
    if w is None or a.program is None:
        return None
    for s in walk(a.program.body):
        if isinstance(s, Namespace) and s.label == w[0] and s.line:
            return s.line - 1
        if isinstance(s, Def) and s.name == w[0] and s.line:
            return s.line - 1
    return None


def format_text(text: str, core: str | None = None) -> str | None:
    if _core(core) == "rust":
        try:
            return _rs.format(text)
        except _rs.KirError:
            return None
    try:
        return write(parse(text))
    except KirSyntaxError:
        return None
