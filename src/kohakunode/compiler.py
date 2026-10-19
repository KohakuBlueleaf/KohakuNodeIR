"""One call from source text to a checked program, its optimized form and hashes."""

from dataclasses import dataclass
from pathlib import Path

from kohakunode.check import Diagnostic, check
from kohakunode.errors import KirCheckError, KirSignatureError
from kohakunode.lower import full_hash, run_passes, semantic_hash
from kohakunode.sig.env import NodeEnv, build_env
from kohakunode.sig.model import Library
from kohakunode.syntax.ast import Program
from kohakunode.syntax.parser import parse


@dataclass
class Compiled:
    program: Program  # as written
    lowered: Program  # after the passes
    env: NodeEnv
    diagnostics: list[Diagnostic]
    semantic_hash: str
    full_hash: str

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]


def compile_program(
    program: Program,
    libraries: list[Library] | None = None,
    base_dir: Path | None = None,
    sig_path: list[Path] | None = None,
    passes: list[str] | None = None,
) -> Compiled:
    """Check, then run the passes (default: all); raise :class:`KirCheckError` on errors."""
    try:
        env = build_env(program, libraries, base_dir, sig_path)
    except KirSignatureError as exc:
        raise KirCheckError([Diagnostic("E002", str(exc))]) from None
    diagnostics = check(program, env)
    if any(d.severity == "error" for d in diagnostics):
        raise KirCheckError(diagnostics)
    lowered = run_passes(program, env, passes)
    env.internal = True
    return Compiled(program, lowered, env, diagnostics, semantic_hash(lowered), full_hash(lowered))


def compile_source(
    source: str,
    libraries: list[Library] | None = None,
    base_dir: Path | None = None,
    sig_path: list[Path] | None = None,
    passes: list[str] | None = None,
) -> Compiled:
    return compile_program(parse(source), libraries, base_dir, sig_path, passes)


def compile_file(
    path: str | Path,
    libraries: list[Library] | None = None,
    sig_path=None,
    passes: list[str] | None = None,
) -> Compiled:
    path = Path(path)
    return compile_source(
        path.read_text(encoding="utf-8"), libraries, path.parent, sig_path, passes
    )
