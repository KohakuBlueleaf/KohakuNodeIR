"""One call from source text to a checked program, its optimized form and hashes."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from kohakunode.check import Diagnostic, check
from kohakunode.errors import KirCheckError, KirSignatureError
from kohakunode.lower import full_hash, run_passes, semantic_hash
from kohakunode.modules import link_program
from kohakunode.sig.env import NodeEnv, build_env, qualify_record_types
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
    source_program: Program | None = None  # before linking; text/graph authoring form
    dependencies: dict = field(default_factory=dict)

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]


def compile_program(
    program: Program,
    libraries: list[Library] | None = None,
    base_dir: Path | None = None,
    sig_path: list[Path] | None = None,
    passes: list[str] | None = None,
    *,
    modules: Mapping[str, str] | None = None,
    source_name: str = "<text>",
) -> Compiled:
    """Link, check, then run passes; source maps avoid filesystem access for imports."""
    source_program = program
    try:
        linked = link_program(
            program, libraries, base_dir, sig_path, modules=modules, source_name=source_name
        )
        program = linked.program
        env = build_env(program, linked.libraries, base_dir, sig_path)
        if env.record_schemas():
            program = qualify_record_types(program, env)
            env = build_env(program, linked.libraries, base_dir, sig_path)
    except KirSignatureError as exc:
        raise KirCheckError([Diagnostic("E002", str(exc))]) from None
    diagnostics = check(program, env)
    if any(d.severity == "error" for d in diagnostics):
        raise KirCheckError(diagnostics)
    lowered = run_passes(program, env, passes)
    env.internal = True
    sem, full = semantic_hash(lowered), full_hash(lowered)
    if linked.dependencies:
        dependency_hash = linked.dependencies["hash"]
        sem = hashlib.sha256(f"{sem}\x1f{dependency_hash}".encode()).hexdigest()
        full = hashlib.sha256(f"{full}\x1f{dependency_hash}".encode()).hexdigest()
    return Compiled(
        program,
        lowered,
        env,
        diagnostics,
        sem,
        full,
        source_program,
        linked.dependencies,
    )


def compile_source(
    source: str,
    libraries: list[Library] | None = None,
    base_dir: Path | None = None,
    sig_path: list[Path] | None = None,
    passes: list[str] | None = None,
    *,
    modules: Mapping[str, str] | None = None,
    source_name: str = "<text>",
) -> Compiled:
    return compile_program(
        parse(source),
        libraries,
        base_dir,
        sig_path,
        passes,
        modules=modules,
        source_name=source_name,
    )


def compile_file(
    path: str | Path,
    libraries: list[Library] | None = None,
    sig_path=None,
    passes: list[str] | None = None,
) -> Compiled:
    path = Path(path)
    return compile_source(
        path.read_text(encoding="utf-8"),
        libraries,
        path.parent,
        sig_path,
        passes,
        source_name=path.name,
    )
