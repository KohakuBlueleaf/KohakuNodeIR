"""Read exported source declarations for editor queries, without loading implementations.

This is an authoring index, not a linker: compilation remains authoritative for
cycles, transitive dependencies, visibility and type checking.
"""

import posixpath
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from kohakunode.errors import KirSyntaxError
from kohakunode.sig.env import NodeEnv
from kohakunode.syntax.ast import Def, Program
from kohakunode.syntax.parser import parse


@dataclass(frozen=True)
class DefinitionLocation:
    path: str | None
    line: int


def exported_definitions(
    program: Program,
    env: NodeEnv,
    base: Path | None,
    source_name: str,
    modules: Mapping[str, str] | None = None,
) -> dict[str, DefinitionLocation]:
    locations = {}
    for imp in program.imports:
        request = imp.module
        if not request or "\\" in request or ":" in request or request.startswith("/"):
            continue
        resource = posixpath.normpath(posixpath.join(posixpath.dirname(source_name), request))
        if resource in (".", "..") or resource.startswith("../"):
            continue
        try:
            path = (base / resource).absolute() if base is not None else None
            if modules is None and path is not None:
                path = path.resolve()
                if not path.is_relative_to(base.resolve()):
                    continue
            if modules is not None:
                text = modules[resource]
            elif path is not None:
                text = path.read_text(encoding="utf-8")
            else:
                continue
            imported = parse(text)
        except (KeyError, OSError, UnicodeError, KirSyntaxError):
            continue  # The compiler reports invalid/missing sources, not this index.
        for stmt in imported.body:
            if isinstance(stmt, Def) and stmt.name in imported.exports:
                name = f"{imp.alias}.{stmt.name}"
                env.defs[name] = replace(stmt, name=name)
                locations[name] = DefinitionLocation(
                    str(path) if path else resource, (stmt.line or 1) - 1
                )
    return locations
