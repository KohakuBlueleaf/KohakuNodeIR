"""Source provenance helpers, independent of KIR text and editor metadata.

Stamp before linking or lowering changes traversal order. Fallback IDs identify
AST traversal paths, so formatting does not affect them; arbitrary edits can.
"""

import copy
from dataclasses import replace

from kohakunode.syntax.ast import Def, Origin, Program, Stmt, children


def stamp_origins(program: Program, module: str = "<text>") -> Program:
    """Return a copy with origins on unstamped statements, preserving explicit origins.

    ``meta.node_id`` overrides the fallback ``body/0/body/1``-style path. Definition
    names and source lines describe the original source, not later lowered names.
    """
    result = copy.deepcopy(program)

    def stamp(stmts: list[Stmt], path: str, definition: str | None) -> None:
        for index, stmt in enumerate(stmts):
            node_path = f"{path}/{index}"
            context = stmt.name if isinstance(stmt, Def) else definition
            if stmt.origin is None:
                node_id = stmt.meta.get("node_id")
                stmt.origin = Origin(
                    module=module,
                    node_id=node_path if node_id is None else str(node_id),
                    line=stmt.line,
                    definition=context,
                )
            for child_index, body in enumerate(children(stmt)):
                field = "body" if child_index == 0 else "handler"
                stamp(body, f"{node_path}/{field}", context)

    stamp(result.body, "body", None)
    return result


def derive_origin(
    origin: Origin | None,
    *,
    generated: str | None = None,
    calls: tuple[Origin, ...] = (),
) -> Origin | None:
    """Retain a source location while appending ancestry or marking a generated operation.

    Missing origins stay missing, supporting direct use of passes on unstamped ASTs.
    A missing ``generated`` argument preserves an existing generated marker.
    Ancestry is a flat outermost-first sequence of shallow call-site locations:
    each entry has empty ``calls``. Nested copies of the same ancestry would make
    serialization exponential in inlining depth without adding information.
    """
    if origin is None:
        return None
    return replace(
        origin,
        calls=tuple(
            replace(call, calls=()) if call.calls else call for call in origin.calls + calls
        ),
        generated=origin.generated if generated is None else generated,
    )
