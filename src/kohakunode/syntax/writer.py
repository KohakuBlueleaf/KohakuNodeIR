"""Print a :class:`Program` as canonical KIR text.

Canonical form: 4-space indentation, one space after commas, `@meta` and
`@hint` each on one line before their statement, blank lines only around
top-level `@def` and `@typehint` blocks. ``parse(write(p)) == p`` for every
program.
"""

import json
import math

from kohakunode.syntax.ast import (
    Arg,
    Assign,
    Branch,
    Call,
    Collect,
    Dataflow,
    Def,
    Each,
    Expr,
    Jump,
    Name,
    Namespace,
    Parallel,
    Program,
    Stmt,
    Switch,
    Try,
    TypeExpr,
    TypeHints,
)

INDENT = "    "


def write_literal(value) -> str:
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"{value} has no KIR literal")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, tuple):
        if len(value) == 1:
            return f"({write_literal(value[0])},)"
        return "(" + ", ".join(write_literal(v) for v in value) + ")"
    if isinstance(value, list):
        return "[" + ", ".join(write_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{write_literal(k)}: {write_literal(v)}" for k, v in value.items())
            + "}"
        )
    raise ValueError(f"{type(value).__name__} has no KIR literal")


def write_expr(e: Expr) -> str:
    return e.id if isinstance(e, Name) else write_literal(e.value)


def write_type(t: TypeExpr) -> str:
    match t.kind:
        case "any":
            return "_"
        case "name":
            return t.name
        case "optional":
            return write_type(t.args[0]) + "?"
        case "generic":
            return f"{t.name}[{', '.join(write_type(a) for a in t.args)}]"
        case "union":
            return " | ".join(write_type(a) for a in t.args)
    raise ValueError(t.kind)


def _arg(a: Arg) -> str:
    return write_expr(a.value) if a.key is None else f"{a.key}={write_expr(a.value)}"


def _pairs(d: dict) -> str:
    return " ".join(f"{k}={write_literal(v)}" for k, v in d.items())


def _call_head(ins: list[str], name: str, outs: list[str]) -> str:
    return f"({', '.join(ins)}){name}({', '.join(outs)})"


def _simple(s: Stmt) -> str:
    match s:
        case Assign():
            t = f": {write_type(s.type)}" if s.type is not None else ""
            return f"{s.target}{t} = {write_expr(s.value)}"
        case Call():
            return _call_head([_arg(a) for a in s.args], s.name, [o or "_" for o in s.outs])
        case Branch():
            return _call_head(
                [write_expr(s.cond)], "branch", [f"`{s.true_label}`", f"`{s.false_label}`"]
            )
        case Switch():
            outs = [f"{write_literal(v)}=>`{label}`" for v, label in s.cases]
            if s.default is not None:
                outs.append(f"_=>`{s.default}`")
            return _call_head([write_expr(s.value)], "switch", outs)
        case Jump():
            return _call_head([], "jump", [f"`{s.label}`"])
        case Parallel():
            return _call_head([], "parallel", [f"`{x}`" for x in s.labels])
        case Collect():
            outs = [s.item or "_"]
            if s.has_index:
                outs.append(s.index or "_")
            outs += [f"`{s.label}`", f"{write_expr(s.value)} -> {s.target}"]
            return _call_head([write_expr(s.items)], "collect", outs)
        case Each():
            outs = [s.item or "_"]
            if s.has_index:
                outs.append(s.index or "_")
            return _call_head([write_expr(s.items)], "each", outs + [f"`{s.label}`"])
    raise TypeError(type(s).__name__)


def _block(stmts: list[Stmt], depth: int, out: list[str]) -> None:
    for s in stmts:
        _stmt(s, depth, out)


def _stmt(s: Stmt, depth: int, out: list[str]) -> None:
    pad = INDENT * depth
    if s.meta:
        out.append(f"{pad}@meta {_pairs(s.meta)}")
    if s.hint:
        out.append(f"{pad}@hint {_pairs(s.hint)}")
    match s:
        case Namespace():
            out.append(f"{pad}{s.label}:")
            _block(s.body, depth + 1, out)
        case Dataflow():
            out.append(f"{pad}@dataflow:")
            _block(s.body, depth + 1, out)
        case Try():
            out.append(f"{pad}@try:")
            _block(s.body, depth + 1, out)
            out.append(f"{pad}@except {s.error_name}:" if s.error_name else f"{pad}@except:")
            _block(s.handler, depth + 1, out)
        case Def():
            params = []
            for p in s.params:
                text = p.name
                if p.type is not None:
                    text += f": {write_type(p.type)}"
                if p.default is not None:
                    text += f" = {write_expr(p.default)}"
                params.append(text)
            outs = [
                o.name + (f": {write_type(o.type)}" if o.type is not None else "")
                for o in s.outputs
            ]
            out.append(f"{pad}@def ({', '.join(params)}){s.name}({', '.join(outs)}):")
            _block(s.body, depth + 1, out)
        case TypeHints():
            out.append(f"{pad}@typehint:")
            for e in s.entries:
                ins = ", ".join(write_type(t) for t in e.inputs)
                outs = ", ".join(write_type(t) for t in e.outputs)
                out.append(f"{pad}{INDENT}({ins}){e.name}({outs})")
        case _:
            out.append(pad + _simple(s))


def write(program: Program) -> str:
    out: list[str] = []
    for u in program.uses:
        out.append(f"@use {write_literal(u.library)}" + (f" as {u.alias}" if u.alias else ""))
    for imp in program.imports:
        out.append(f"@import {write_literal(imp.module)} as {imp.alias}")
    for name in program.exports:
        out.append(f"@export {name}")
    if program.mode:
        out.append(f"@mode {program.mode}")
    if out:
        out.append("")
    previous_compound = False
    for s in program.body:
        compound = isinstance(s, (Def, TypeHints))
        if out and out[-1] != "" and (compound or previous_compound):
            out.append("")
        _stmt(s, 0, out)
        previous_compound = compound
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def write_statement(s: Stmt) -> str:
    return _simple(s)
