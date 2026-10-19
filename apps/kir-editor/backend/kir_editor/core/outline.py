"""The block structure of a program, for the editor's Scratch-like view.

Every statement becomes ``{"kind", "text", "line"}``; a statement holding
statements adds ``"slots"``: ``[{"label", "body"}]``, one per nested block
(a namespace has one, ``@try`` has two).
"""

from kohakunode.syntax.ast import (
    Assign,
    Call,
    Dataflow,
    Def,
    Namespace,
    Program,
    Stmt,
    Try,
    TypeHints,
)
from kohakunode.syntax.writer import write_expr, write_statement, write_type

BUILTIN_KIND = {
    "Branch": "branch",
    "Switch": "switch",
    "Jump": "jump",
    "Parallel": "parallel",
    "Each": "each",
}


def _def_head(s: Def) -> str:
    params = []
    for p in s.params:
        text = p.name
        if p.type is not None:
            text += f": {write_type(p.type)}"
        if p.default is not None:
            text += f" = {write_expr(p.default)}"
        params.append(text)
    outs = [o.name + (f": {write_type(o.type)}" if o.type is not None else "") for o in s.outputs]
    return f"@def ({', '.join(params)}){s.name}({', '.join(outs)})"


def _block(stmts: list[Stmt]) -> list[dict]:
    return [_stmt(s) for s in stmts]


def _stmt(s: Stmt) -> dict:
    out: dict = {"line": s.line}
    if s.meta:
        out["meta"] = {k: list(v) if isinstance(v, tuple) else v for k, v in s.meta.items()}
    if s.hint:
        out["hint"] = dict(s.hint)
    match s:
        case Namespace():
            out |= {"kind": "namespace", "text": f"{s.label}:", "label": s.label}
            out["slots"] = [{"label": s.label, "body": _block(s.body)}]
        case Dataflow():
            out |= {"kind": "dataflow", "text": "@dataflow:"}
            out["slots"] = [{"label": "dataflow", "body": _block(s.body)}]
        case Try():
            out |= {"kind": "try", "text": "@try:"}
            handler = f"@except {s.error_name}" if s.error_name else "@except"
            out["slots"] = [
                {"label": "try", "body": _block(s.body)},
                {"label": handler, "body": _block(s.handler)},
            ]
        case Def():
            out |= {"kind": "def", "text": _def_head(s) + ":", "name": s.name}
            out["slots"] = [{"label": s.name, "body": _block(s.body)}]
        case TypeHints():
            entries = [
                f"({', '.join(write_type(t) for t in e.inputs)}){e.name}"
                f"({', '.join(write_type(t) for t in e.outputs)})"
                for e in s.entries
            ]
            out |= {"kind": "typehint", "text": "@typehint:", "entries": entries}
        case Assign():
            out |= {"kind": "assign", "text": write_statement(s)}
        case Call():
            out |= {"kind": "call", "text": write_statement(s), "name": s.name}
        case _:
            out |= {"kind": BUILTIN_KIND[type(s).__name__], "text": write_statement(s)}
    return out


def outline(program: Program) -> dict:
    """``{"uses": [...], "mode", "body": [...]}`` for one program."""
    return {
        "uses": [{"library": u.library, "alias": u.alias} for u in program.uses],
        "mode": program.mode,
        "body": _block(program.body),
    }
