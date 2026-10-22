"""KIR programs as JSON, both ways, for the editor's statement views (blocks, sequence).

Every statement is ``{"type", "line", "meta"?, "hint"?, ...fields}``; an
expression is ``{"name": "x"}`` or ``{"lit": <literal>}``; a type is its KIR
text (``"list[Box]"``) or null. Literals (also the values of ``meta`` and
``hint``) use the graph file's encoding (graph.md): tuples as
``{"tuple": [...]}``, dicts as ``{"dict": {...}}`` or ``{"pairs": [[k, v], ...]}``.
"""

from kohakunode.graph.from_graph import decode_literal
from kohakunode.sig.types import parse_type
from kohakunode.syntax.ast import (
    Arg,
    Assign,
    Branch,
    Call,
    Dataflow,
    Def,
    Each,
    Import,
    Jump,
    Literal,
    Name,
    Namespace,
    OutParam,
    Parallel,
    Param,
    Program,
    Stmt,
    Switch,
    Try,
    TypeHintEntry,
    TypeHints,
    Use,
)
from kohakunode.syntax.writer import write_type


class AstJsonError(ValueError):
    """A JSON program that does not describe valid statements."""


# ---------------------------------------------------------------- literals, expressions, types


def encode_literal(v):
    if isinstance(v, tuple):
        return {"tuple": [encode_literal(x) for x in v]}
    if isinstance(v, list):
        return [encode_literal(x) for x in v]
    if isinstance(v, dict):
        if all(isinstance(k, str) for k in v):
            return {"dict": {k: encode_literal(x) for k, x in v.items()}}
        return {"pairs": [[encode_literal(k), encode_literal(x)] for k, x in v.items()]}
    return v


def _expr(e) -> dict:
    return {"name": e.id} if isinstance(e, Name) else {"lit": encode_literal(e.value)}


def _expr_from(d) -> Name | Literal:
    if not isinstance(d, dict) or ("name" in d) == ("lit" in d):
        raise AstJsonError(f"bad expression {d!r}")
    return Name(d["name"]) if "name" in d else Literal(decode_literal(d["lit"]))


def _type(t) -> str | None:
    return None if t is None else write_type(t)


def _type_from(t):
    return None if t in (None, "") else parse_type(t)


def _pairs_json(pairs: dict) -> dict:
    """`@meta` / `@hint` values, in the literal encoding (a tuple stays a tuple)."""
    return {k: encode_literal(v) for k, v in pairs.items()}


def _pairs_from(pairs: dict) -> dict:
    return {k: decode_literal(v) for k, v in pairs.items()}


# ---------------------------------------------------------------- to JSON


def stmt_to_json(s: Stmt) -> dict:
    out: dict = {"line": s.line}
    if s.meta:
        out["meta"] = _pairs_json(s.meta)
    if s.hint:
        out["hint"] = _pairs_json(s.hint)
    match s:
        case Assign():
            out |= {
                "type": "assign",
                "target": s.target,
                "value": _expr(s.value),
                "vtype": _type(s.type),
            }
        case Call():
            out |= {
                "type": "call",
                "name": s.name,
                "args": [{"value": _expr(a.value), "key": a.key} for a in s.args],
                "outs": list(s.outs),
            }
        case Branch():
            out |= {
                "type": "branch",
                "cond": _expr(s.cond),
                "true_label": s.true_label,
                "false_label": s.false_label,
            }
        case Switch():
            out |= {
                "type": "switch",
                "value": _expr(s.value),
                "cases": [[encode_literal(v), label] for v, label in s.cases],
                "default": s.default,
            }
        case Jump():
            out |= {"type": "jump", "label": s.label}
        case Parallel():
            out |= {"type": "parallel", "labels": list(s.labels)}
        case Each():
            out |= {
                "type": "each",
                "items": _expr(s.items),
                "item": s.item,
                "index": s.index,
                "label": s.label,
                "has_index": s.has_index,
            }
        case Namespace():
            out |= {"type": "namespace", "label": s.label, "body": block_to_json(s.body)}
        case Dataflow():
            out |= {"type": "dataflow", "body": block_to_json(s.body)}
        case Try():
            out |= {
                "type": "try",
                "body": block_to_json(s.body),
                "handler": block_to_json(s.handler),
                "error_name": s.error_name,
            }
        case Def():
            out |= {
                "type": "def",
                "name": s.name,
                "params": [
                    {
                        "name": p.name,
                        "type": _type(p.type),
                        "default": None if p.default is None else _expr(p.default),
                    }
                    for p in s.params
                ],
                "outputs": [{"name": o.name, "type": _type(o.type)} for o in s.outputs],
                "body": block_to_json(s.body),
            }
        case TypeHints():
            out |= {
                "type": "typehints",
                "entries": [
                    {
                        "name": e.name,
                        "inputs": [write_type(t) for t in e.inputs],
                        "outputs": [write_type(t) for t in e.outputs],
                    }
                    for e in s.entries
                ],
            }
        case _:
            raise AstJsonError(f"unknown statement {type(s).__name__}")
    return out


def block_to_json(stmts: list[Stmt]) -> list[dict]:
    return [stmt_to_json(s) for s in stmts]


def program_to_json(p: Program) -> dict:
    return {
        "uses": [{"library": u.library, "alias": u.alias} for u in p.uses],
        "imports": [{"module": i.module, "alias": i.alias} for i in p.imports],
        "exports": list(p.exports),
        "mode": p.mode,
        "body": block_to_json(p.body),
    }


# ---------------------------------------------------------------- from JSON


def _block_from(items) -> list[Stmt]:
    if not isinstance(items, list):
        raise AstJsonError(f"a block is a list, not {items!r}")
    return [stmt_from_json(d) for d in items]


def _build(d: dict) -> Stmt:
    match d.get("type"):
        case "assign":
            return Assign(d["target"], _expr_from(d["value"]), _type_from(d.get("vtype")))
        case "call":
            return Call(
                d["name"],
                [Arg(_expr_from(a["value"]), a.get("key")) for a in d.get("args", [])],
                list(d.get("outs", [])),
            )
        case "branch":
            return Branch(_expr_from(d["cond"]), d["true_label"], d["false_label"])
        case "switch":
            return Switch(
                _expr_from(d["value"]),
                [(decode_literal(v), label) for v, label in d.get("cases", [])],
                d.get("default"),
            )
        case "jump":
            return Jump(d["label"])
        case "parallel":
            return Parallel(list(d["labels"]))
        case "each":
            return Each(
                _expr_from(d["items"]),
                d.get("item"),
                d.get("index"),
                d["label"],
                bool(d.get("has_index")),
            )
        case "namespace":
            return Namespace(d["label"], _block_from(d.get("body", [])))
        case "dataflow":
            return Dataflow(_block_from(d.get("body", [])))
        case "try":
            return Try(
                _block_from(d.get("body", [])),
                _block_from(d.get("handler", [])),
                d.get("error_name"),
            )
        case "def":
            return Def(
                d["name"],
                [
                    Param(
                        p["name"],
                        _type_from(p.get("type")),
                        None if p.get("default") is None else _expr_from(p["default"]),
                    )
                    for p in d.get("params", [])
                ],
                [OutParam(o["name"], _type_from(o.get("type"))) for o in d.get("outputs", [])],
                _block_from(d.get("body", [])),
            )
        case "typehints":
            return TypeHints(
                [
                    TypeHintEntry(
                        e["name"],
                        tuple(parse_type(t) for t in e["inputs"]),
                        tuple(parse_type(t) for t in e["outputs"]),
                    )
                    for e in d["entries"]
                ]
            )
    raise AstJsonError(f"unknown statement type {d.get('type')!r}")


def stmt_from_json(d: dict) -> Stmt:
    if not isinstance(d, dict):
        raise AstJsonError(f"a statement is an object, not {d!r}")
    try:
        s = _build(d)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AstJsonError):
            raise
        raise AstJsonError(f"bad {d.get('type')} statement: {exc!r}") from None
    s.meta = _pairs_from(d.get("meta") or {})
    s.hint = _pairs_from(d.get("hint") or {})
    return s


def program_from_json(d: dict) -> Program:
    if not isinstance(d, dict):
        raise AstJsonError("a program is an object")
    imports = d.get("imports", [])
    exports = d.get("exports", [])
    if not isinstance(imports, list) or any(
        not isinstance(i, dict)
        or not isinstance(i.get("module"), str)
        or not isinstance(i.get("alias"), str)
        for i in imports
    ):
        raise AstJsonError("imports must be a list of objects with module and alias strings")
    if not isinstance(exports, list) or any(not isinstance(e, str) for e in exports):
        raise AstJsonError("exports must be a list of definition names")
    return Program(
        uses=[Use(u["library"], u.get("alias")) for u in d.get("uses", [])],
        body=_block_from(d.get("body", [])),
        mode=d.get("mode"),
        imports=[Import(i["module"], i["alias"]) for i in imports],
        exports=list(exports),
    )
