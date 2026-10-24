"""Every editor operation as one call into ``kohakunode``.

Results are plain JSON-ready dicts. A user error (bad syntax, unknown library,
failed check, a node raising at run time) is never an exception here: it comes
back in ``diagnostics`` as ``{"code", "severity", "message", "line", "column"}``.
"""

import contextlib
import io
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from kohakunode import (
    STD,
    Interpreter,
    KirCheckError,
    KirError,
    KirRuntimeError,
    KirSignatureError,
    KirSyntaxError,
    check,
    compile_program,
    parse,
    write,
)
from kohakunode.errors import KirGraphError
from kohakunode.graph import from_graph, to_graph
from kohakunode.graph.to_graph import DATA_STYLES
from kohakunode.lower.passes import PASSES, REQUIRES
from kohakunode.sig import Library, NodeEnv, build_env, library_from_json, library_to_json
from kohakunode.sig.files import SUFFIX, load_library
from kohakunode.syntax.ast import Program

from kir_editor.config import Settings
from kir_editor.core.ast_json import (
    AstJsonError,
    program_from_json,
    program_to_json,
)
from kir_editor.core.demo_nodes import DEMO

# A run redirects the process's stdout; runs take turns so their output never mixes.
_RUN_LOCK = threading.Lock()


@dataclass
class Scope:
    """Libraries handed to the toolchain directly, beside those `@use` finds on the signature path.

    ``signatures`` are parsed ``.kirsig.json`` files the client holds. ``use_demo``
    gives the runnable ``demo`` library unaliased; a program that writes
    ``@use "demo"`` gets it either way. Two given libraries that share a node
    name make an unaliased call to it ambiguous (E011), so a client loading a
    library that overlaps ``demo`` turns ``use_demo`` off.
    """

    signatures: list[dict] = field(default_factory=list)
    use_demo: bool = True
    modules: dict[str, str] | None = None
    source_name: str = "<text>"


def diagnostic(code: str, message: str, line: int | None = None, column: int | None = None):
    return {
        "code": code,
        "severity": "warning" if code.startswith("W") else "error",
        "message": message,
        "line": line,
        "column": column,
    }


def _from_error(exc: KirError) -> list[dict]:
    if isinstance(exc, KirCheckError):
        return [diagnostic(d.code, d.message, d.line) for d in exc.diagnostics]
    if isinstance(exc, KirSyntaxError):
        return [diagnostic("E001", str(exc), exc.line, exc.column)]
    if isinstance(exc, KirSignatureError):
        return [diagnostic("E002", str(exc))]
    if isinstance(exc, KirGraphError):
        return [diagnostic("graph", str(exc))]
    if isinstance(exc, KirRuntimeError):
        return [diagnostic("runtime", str(exc), exc.line)]
    return [diagnostic("error", str(exc))]


def _found(diagnostics) -> list[dict]:
    return [diagnostic(d.code, d.message, d.line) for d in diagnostics]


def _json_safe(value):
    """Final values as JSON; anything JSON cannot hold is shown by its repr."""
    return json.loads(json.dumps(value, default=repr))


class Toolchain:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ------------------------------------------------------------ libraries
    def libraries(self, program: Program, scope: Scope) -> list[Library]:
        libs = []
        if scope.use_demo or any(u.library == DEMO.name for u in program.uses):
            libs.append(DEMO)
        for data in scope.signatures:
            try:
                lib = library_from_json(data)
            except (KeyError, TypeError, ValueError) as exc:
                raise KirSignatureError(f"malformed signature file: {exc!r}") from None
            if lib.name != DEMO.name:
                libs.append(lib)
        return libs

    def passes(self) -> list[dict]:
        """The optimization passes in run order, with the passes each needs before it."""
        return [
            {"name": name, "doc": (fn.__doc__ or "").strip(), "needs": list(REQUIRES.get(name, []))}
            for name, fn in PASSES.items()
        ]

    def catalog(self) -> list[dict]:
        """Every library the backend knows: ``kir.std``, ``demo``, then the signature directories."""
        out = [
            {"source": "builtin", "runnable": True, **library_to_json(STD)},
            {"source": "demo", "runnable": True, **library_to_json(DEMO)},
        ]
        for d in self.settings.sig_dirs:
            for path in sorted(Path(d).glob(f"*{SUFFIX}")):
                try:
                    lib = load_library(path)
                except KirSignatureError as exc:
                    out.append({"source": path.name, "error": str(exc), "nodes": []})
                    continue
                data = library_to_json(lib)
                out.append(
                    {
                        "source": path.name,
                        "runnable": bool(lib.records) and not data["nodes"],
                        **data,
                    }
                )
        return out

    # ------------------------------------------------------------ views
    def checked(self, program: Program, scope: Scope) -> tuple[NodeEnv | None, list[dict]]:
        """The program's environment (None when a library fails to load) and its diagnostics."""
        try:
            env = build_env(program, self.libraries(program, scope), None, self.settings.sig_dirs)
        except KirError as exc:
            return None, _from_error(exc)
        if program.imports or program.exports or env.record_schemas():
            try:
                compiled = compile_program(
                    program,
                    self.libraries(program, scope),
                    None,
                    self.settings.sig_dirs,
                    [],
                    modules=scope.modules,
                    source_name=scope.source_name,
                )
                return env, _found(compiled.diagnostics)
            except KirError as exc:
                return env, _from_error(exc)
        return env, _found(check(program, env))

    def graph(self, text: str, scope: Scope, data: str = "wires") -> dict:
        """Text -> graph view (.kirgraph) in a data style, with the AST and diagnostics."""
        try:
            program = parse(text)
        except KirError as exc:
            return {"graph": None, "ast": None, "diagnostics": _from_error(exc)}
        if data not in DATA_STYLES:
            return {
                "graph": None,
                "ast": None,
                "diagnostics": [diagnostic("error", f"unknown data style {data!r}")],
            }
        env, diagnostics = self.checked(program, scope)
        return {
            "graph": to_graph(program, env, data=data),
            "ast": program_to_json(program),
            "diagnostics": diagnostics,
        }

    def text(self, graph: dict, scope: Scope, with_meta: bool) -> dict:
        """Graph view -> canonical text, with the AST and diagnostics."""
        try:
            text = write(from_graph(graph, with_meta=with_meta))
            program = parse(text)
        except (KirError, KeyError, TypeError, ValueError) as exc:
            err = exc if isinstance(exc, KirError) else KirGraphError(f"malformed graph: {exc!r}")
            return {"text": None, "ast": None, "diagnostics": _from_error(err)}
        _, diagnostics = self.checked(program, scope)
        return {
            "text": text,
            "ast": program_to_json(program),
            "diagnostics": diagnostics,
        }

    def ast_text(self, ast: dict, scope: Scope) -> dict:
        """AST JSON (as the statement views edit it) -> canonical text and its diagnostics."""
        try:
            text = write(program_from_json(ast))
            program = parse(text)
        except (KirError, AstJsonError) as exc:
            err = exc if isinstance(exc, KirError) else KirError(str(exc))
            return {"text": None, "diagnostics": _from_error(err)}
        return {"text": text, "diagnostics": self.checked(program, scope)[1]}

    def check(self, text: str, scope: Scope) -> dict:
        try:
            program = parse(text)
        except KirError as exc:
            return {"diagnostics": _from_error(exc)}
        return {"diagnostics": self.checked(program, scope)[1]}

    # ------------------------------------------------------------ compile and run
    def _compile(self, text: str, scope: Scope, passes: list[str] | None):
        program = parse(text)
        try:
            return compile_program(
                program,
                self.libraries(program, scope),
                None,
                self.settings.sig_dirs,
                passes,
                modules=scope.modules,
                source_name=scope.source_name,
            )
        except ValueError as exc:  # an unknown pass, or one listed before a pass it needs
            raise KirError(str(exc)) from None

    def lower(self, text: str, scope: Scope, passes: list[str] | None = None) -> dict:
        """Text -> the program after the optimization passes (default: all), and its hashes."""
        try:
            compiled = self._compile(text, scope, passes)
        except KirError as exc:
            return {
                "lowered": None,
                "semantic_hash": None,
                "full_hash": None,
                "diagnostics": _from_error(exc),
            }
        return {
            "lowered": write(compiled.lowered),
            "semantic_hash": compiled.semantic_hash,
            "full_hash": compiled.full_hash,
            "diagnostics": _found(compiled.diagnostics),
        }

    def run(self, text: str, scope: Scope, passes: list[str] | None = None) -> dict:
        """Run the program after ``passes`` (default: all; [] runs it as written)."""
        try:
            compiled = self._compile(text, scope, passes)
        except KirError as exc:
            return {"ok": False, "values": {}, "stdout": "", "diagnostics": _from_error(exc)}
        diagnostics = _found(compiled.diagnostics)
        interp = Interpreter(compiled.lowered, compiled.env, step_budget=self.settings.step_budget)
        buf = io.StringIO()
        ok = True
        with _RUN_LOCK, contextlib.redirect_stdout(buf):
            try:
                interp.run()
            except KirError as exc:
                ok = False
                diagnostics += _from_error(exc)
        return {
            "ok": ok,
            "values": _json_safe(interp.source_values()),
            "stdout": buf.getvalue(),
            "diagnostics": diagnostics,
        }
