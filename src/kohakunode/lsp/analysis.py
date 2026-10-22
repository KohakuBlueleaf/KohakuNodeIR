"""Editor queries over KIR text, independent of any protocol.

Positions are 0-based (line, character), as in LSP. Diagnostics and
formatting come from one of two cores: "python" (the reference) or "rust"
(``kohakunode._rs``, byte-identical on the golden corpus). Hover, completion
and go-to-definition read the program structure from the Python parser.
"""

import json
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

try:
    from kohakunode import _rs
except ImportError:  # a source tree without the built extension
    _rs = None

from kohakunode.check import check
from kohakunode.compiler import compile_program
from kohakunode.errors import KirCheckError, KirSignatureError, KirSyntaxError
from kohakunode.lsp.modules import DefinitionLocation, exported_definitions
from kohakunode.sig.env import NodeEnv, Resolved, build_env
from kohakunode.sig.model import Signature
from kohakunode.sig.std import STD
from kohakunode.sig.types import type_text
from kohakunode.syntax.ast import BUILTINS, Def, Namespace, Program, walk
from kohakunode.syntax.parser import parse
from kohakunode.syntax.writer import write

DIRECTIVES = [
    "use",
    "import",
    "export",
    "def",
    "meta",
    "hint",
    "dataflow",
    "try",
    "except",
    "typehint",
    "mode",
]
_MODULE_DIRECTIVE = re.compile(r"^\s*@(?:import|export)\b", re.MULTILINE)
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


def _module_core(core: str, modular: bool) -> str:
    """Older wheels predate module syntax/linking; make that fallback visible."""
    if core == "rust" and modular and not hasattr(_rs, "compile_modules"):
        warnings.warn(
            "The installed Rust extension lacks source-module support; using the Python "
            "reference for this document. Rebuild kohakunode._rs to use the native linker.",
            RuntimeWarning,
            stacklevel=3,
        )
        return "python"
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
    imported_definitions: dict[str, DefinitionLocation] = field(default_factory=dict)


def analyze(
    text: str,
    path: str | None = None,
    sig_path: list[str] = (),
    core: str | None = None,
    *,
    modules: Mapping[str, str] | None = None,
    source_name: str | None = None,
) -> Analysis:
    core = _core(core)
    modular = bool(_MODULE_DIRECTIVE.search(text))
    core = _module_core(core, modular)
    source_name = source_name or (Path(path).name if path else "<text>")
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

    if modular and isinstance(python_error, KirSyntaxError):
        # A half-typed call must not erase the imported completion catalog.
        # This recovery supplies queries only; the selected core diagnoses the
        # original, unmodified source below.
        preamble = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "@use ", "@import ", "@export ")):
                break
            preamble.append(line)
        try:
            program = parse("\n".join(preamble) + "\n")
            env = build_env(program, None, base, [Path(p) for p in sig_path])
        except (KirSyntaxError, KirSignatureError):
            pass
    locations = (
        exported_definitions(program, env, base, source_name, modules)
        if modular and program is not None and env is not None
        else {}
    )

    if core == "rust":
        try:
            if modular:
                result = _rs.compile_modules(
                    text,
                    json.dumps(dict(modules)) if modules is not None else None,
                    source_name,
                    passes=[],
                    base=str(base) if base else None,
                    sig_path=list(sig_path),
                )
                diagnostics = json.loads(result)["diagnostics"]
            else:
                diagnostics = json.loads(
                    _rs.check(text, [], base=str(base) if base else None, sig_path=list(sig_path))
                )
        except _rs.KirSyntaxError as exc:
            message = str(exc)
            where = _WHERE.search(message)
            line, column = (int(where[1]), int(where[2])) if where else (None, None)
            return Analysis(program, env, [syntax(message, line, column)], locations)
        except _rs.KirCheckError as exc:
            diagnostics = json.loads(exc.diagnostics)
        except _rs.KirSignatureError as exc:
            diagnostics = [{"code": "E002", "severity": "error", "message": str(exc), "line": None}]
    else:
        if isinstance(python_error, KirSyntaxError):
            exc = python_error
            return Analysis(program, env, [syntax(str(exc), exc.line, exc.column)], locations)
        if isinstance(python_error, KirSignatureError) and not modular:
            return Analysis(program, None, [found("E002", "error", str(python_error), None)])
        if modular:
            try:
                compiled = compile_program(
                    program,
                    base_dir=base,
                    sig_path=[Path(p) for p in sig_path],
                    passes=[],
                    modules=modules,
                    source_name=source_name,
                )
                checked = compiled.diagnostics
            except KirCheckError as exc:
                checked = exc.diagnostics
        else:
            checked = check(program, env)
        diagnostics = [
            {"code": d.code, "severity": d.severity, "message": d.message, "line": d.line}
            for d in checked
        ]

    # Imported lines are not positions in this document. Keep the compiler's
    # source-aware message, and anchor those errors on the import preamble.
    import_line = next(
        (i + 1 for i, line in enumerate(lines) if line.lstrip().startswith("@import")), 1
    )
    problems = []
    for d in diagnostics:
        line, message = d["line"], d["message"]
        if modular:
            foreign = re.match(r"([^:]+)(?:::.*)?: ", message)
            if d["code"] == "E002" or (foreign and foreign[1] != source_name):
                line = import_line
            if line != d["line"] and d["line"] is not None:
                message += f" (source line {d['line']})"
        problems.append(found(d["code"], d["severity"], message, line))
    return Analysis(program, env, problems, locations)


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
        result = signature_markdown(r.signature, lib)
        location = a.imported_definitions.get(word)
        if location:
            result += f"\n\nsource `{location.path}` (line {location.line + 1})"
        return result
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


def definition_location(
    a: Analysis,
    text: str,
    line: int,
    character: int,
    path: str | None = None,
) -> DefinitionLocation | None:
    """Cross-file definition target; ``definition`` retains its local-line API."""
    word = word_at(text, line, character)
    if word and word[0] in a.imported_definitions:
        return a.imported_definitions[word[0]]
    local = definition(a, text, line, character)
    return None if local is None else DefinitionLocation(path, local)


def signature_help(a: Analysis, text: str, line: int, character: int) -> str | None:
    """Signature at a node name or within its output list (KIR puts inputs first)."""
    result = hover(a, text, line, character)
    if result is not None:
        return result
    lines = text.splitlines()
    if line >= len(lines):
        return None
    matches = list(
        re.finditer(r"\)\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\([^)]*$", lines[line][:character])
    )
    if not matches:
        return None
    return hover(a, text, line, matches[-1].start(1))


def format_text(text: str, core: str | None = None) -> str | None:
    if _module_core(_core(core), bool(_MODULE_DIRECTIVE.search(text))) == "rust":
        try:
            return _rs.format(text)
        except _rs.KirError:
            return None
    try:
        return write(parse(text))
    except KirSyntaxError:
        return None
