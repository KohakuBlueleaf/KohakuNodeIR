"""JSON serialization for KIR AST — bridges Python dataclasses and Rust serde format.

The JSON format matches what kohakunode-rs produces/consumes via serde:
- Statement discriminator: {"type": "FuncCall", ...}
- Expression discriminator: {"type": "Identifier", ...}
"""

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    Expression,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    LabelRef,
    Literal,
    MetaAnnotation,
    ModeDecl,
    Namespace,
    Parallel,
    Parameter,
    Program,
    Statement,
    SubgraphDef,
    Switch,
    TryExcept,
    TypeExpr,
    TypeHintBlock,
    TypeHintEntry,
    Wildcard,
)


# ---------------------------------------------------------------------------
# Python → dict (for JSON serialization)
# ---------------------------------------------------------------------------


def program_to_dict(prog: Program) -> dict:
    d = {"body": [_stmt(s) for s in prog.body]}
    if prog.mode:
        d["mode"] = prog.mode
    if prog.typehints:
        d["typehints"] = [_typehint_entry(e) for e in prog.typehints]
    if prog.line is not None:
        d["line"] = prog.line
    return d


def _stmt(stmt: Statement) -> dict:
    match stmt:
        case Assignment():
            d = {
                "type": "Assignment",
                "target": stmt.target,
                "value": _expr(stmt.value),
            }
            if stmt.type_annotation:
                d["type_annotation"] = _type_expr(stmt.type_annotation)
            if stmt.metadata:
                d["metadata"] = [_meta(m) for m in stmt.metadata]
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case FuncCall():
            d = {
                "type": "FuncCall",
                "func_name": stmt.func_name,
                "inputs": [_expr(e) for e in stmt.inputs],
                "outputs": [_output(o) for o in stmt.outputs],
            }
            if stmt.metadata:
                d["metadata"] = [_meta(m) for m in stmt.metadata]
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case Branch():
            d = {
                "type": "Branch",
                "condition": _expr(stmt.condition),
                "true_label": stmt.true_label,
                "false_label": stmt.false_label,
            }
            if stmt.metadata:
                d["metadata"] = [_meta(m) for m in stmt.metadata]
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case Switch():
            d = {
                "type": "Switch",
                "value": _expr(stmt.value),
                "cases": [[_expr(e), label] for e, label in stmt.cases],
            }
            if stmt.default_label:
                d["default_label"] = stmt.default_label
            if stmt.metadata:
                d["metadata"] = [_meta(m) for m in stmt.metadata]
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case Jump():
            d = {"type": "Jump", "target": stmt.target}
            if stmt.metadata:
                d["metadata"] = [_meta(m) for m in stmt.metadata]
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case Parallel():
            d = {"type": "Parallel", "labels": stmt.labels}
            if stmt.metadata:
                d["metadata"] = [_meta(m) for m in stmt.metadata]
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case Namespace():
            d = {
                "type": "Namespace",
                "name": stmt.name,
                "body": [_stmt(s) for s in stmt.body],
            }
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case DataflowBlock():
            d = {"type": "DataflowBlock", "body": [_stmt(s) for s in stmt.body]}
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case SubgraphDef():
            d = {
                "type": "SubgraphDef",
                "name": stmt.name,
                "params": [_param(p) for p in stmt.params],
                "outputs": stmt.outputs,
                "body": [_stmt(s) for s in stmt.body],
            }
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case ModeDecl():
            d = {"type": "ModeDecl", "mode": stmt.mode}
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case TypeHintBlock():
            d = {
                "type": "TypeHintBlock",
                "entries": [_typehint_entry(e) for e in stmt.entries],
            }
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
        case TryExcept():
            d = {
                "type": "TryExcept",
                "try_body": [_stmt(s) for s in stmt.try_body],
                "except_body": [_stmt(s) for s in stmt.except_body],
            }
            if stmt.metadata:
                d["metadata"] = [_meta(m) for m in stmt.metadata]
            if stmt.line is not None:
                d["line"] = stmt.line
            return d
    return {"type": "Unknown"}


def _expr(expr) -> dict:
    if isinstance(expr, Identifier):
        d = {"type": "Identifier", "name": expr.name}
        if expr.line is not None:
            d["line"] = expr.line
        return d
    if isinstance(expr, Literal):
        d = {
            "type": "Literal",
            "value": _value(expr.value),
            "literal_type": expr.literal_type,
        }
        if expr.line is not None:
            d["line"] = expr.line
        return d
    if isinstance(expr, KeywordArg):
        d = {"type": "KeywordArg", "name": expr.name, "value": _expr(expr.value)}
        if expr.line is not None:
            d["line"] = expr.line
        return d
    if isinstance(expr, LabelRef):
        d = {"type": "LabelRef", "name": expr.name}
        if expr.line is not None:
            d["line"] = expr.line
        return d
    if isinstance(expr, Wildcard):
        d = {"type": "Wildcard"}
        if expr.line is not None:
            d["line"] = expr.line
        return d
    return {"type": "Unknown"}


def _value(v):
    if v is None:
        return None
    return v


def _output(o) -> dict | str:
    if isinstance(o, Wildcard):
        return {"type": "Wildcard"}
    return str(o)


def _meta(m: MetaAnnotation) -> dict:
    return {"data": m.data}


def _param(p: Parameter) -> dict:
    d = {"name": p.name}
    if p.default is not None:
        d["default"] = _expr(p.default)
    return d


def _type_expr(t: TypeExpr) -> dict:
    d = {"name": t.name}
    if t.is_optional:
        d["is_optional"] = True
    if t.union_of:
        d["union_of"] = [_type_expr(u) for u in t.union_of]
    return d


def _typehint_entry(e: TypeHintEntry) -> dict:
    return {
        "func_name": e.func_name,
        "input_types": [_type_expr(t) for t in e.input_types],
        "output_types": [_type_expr(t) for t in e.output_types],
    }


# ---------------------------------------------------------------------------
# dict → Python (from JSON deserialization)
# ---------------------------------------------------------------------------


def dict_to_program(d: dict) -> Program:
    return Program(
        body=[_dict_to_stmt(s) for s in d.get("body", [])],
        mode=d.get("mode"),
        typehints=(
            [_dict_to_typehint_entry(e) for e in d["typehints"]]
            if d.get("typehints")
            else None
        ),
        line=d.get("line"),
    )


def _dict_to_stmt(d: dict) -> Statement:
    t = d.get("type", "")
    match t:
        case "Assignment":
            return Assignment(
                target=d["target"],
                value=_dict_to_expr(d["value"]),
                type_annotation=(
                    _dict_to_type_expr(d["type_annotation"])
                    if d.get("type_annotation")
                    else None
                ),
                metadata=(
                    [_dict_to_meta(m) for m in d["metadata"]]
                    if d.get("metadata")
                    else None
                ),
                line=d.get("line"),
            )
        case "FuncCall":
            return FuncCall(
                func_name=d["func_name"],
                inputs=[_dict_to_expr(e) for e in d.get("inputs", [])],
                outputs=[_dict_to_output(o) for o in d.get("outputs", [])],
                metadata=(
                    [_dict_to_meta(m) for m in d["metadata"]]
                    if d.get("metadata")
                    else None
                ),
                line=d.get("line"),
            )
        case "Branch":
            return Branch(
                condition=_dict_to_expr(d["condition"]),
                true_label=d["true_label"],
                false_label=d["false_label"],
                metadata=(
                    [_dict_to_meta(m) for m in d["metadata"]]
                    if d.get("metadata")
                    else None
                ),
                line=d.get("line"),
            )
        case "Switch":
            return Switch(
                value=_dict_to_expr(d["value"]),
                cases=[(_dict_to_expr(c[0]), c[1]) for c in d.get("cases", [])],
                default_label=d.get("default_label"),
                metadata=(
                    [_dict_to_meta(m) for m in d["metadata"]]
                    if d.get("metadata")
                    else None
                ),
                line=d.get("line"),
            )
        case "Jump":
            return Jump(
                target=d["target"],
                metadata=(
                    [_dict_to_meta(m) for m in d["metadata"]]
                    if d.get("metadata")
                    else None
                ),
                line=d.get("line"),
            )
        case "Parallel":
            return Parallel(
                labels=d.get("labels", []),
                metadata=(
                    [_dict_to_meta(m) for m in d["metadata"]]
                    if d.get("metadata")
                    else None
                ),
                line=d.get("line"),
            )
        case "Namespace":
            return Namespace(
                name=d["name"],
                body=[_dict_to_stmt(s) for s in d.get("body", [])],
                line=d.get("line"),
            )
        case "DataflowBlock":
            return DataflowBlock(
                body=[_dict_to_stmt(s) for s in d.get("body", [])],
                line=d.get("line"),
            )
        case "SubgraphDef":
            return SubgraphDef(
                name=d["name"],
                params=[_dict_to_param(p) for p in d.get("params", [])],
                outputs=d.get("outputs", []),
                body=[_dict_to_stmt(s) for s in d.get("body", [])],
                line=d.get("line"),
            )
        case "ModeDecl":
            return ModeDecl(mode=d["mode"], line=d.get("line"))
        case "TypeHintBlock":
            return TypeHintBlock(
                entries=[_dict_to_typehint_entry(e) for e in d.get("entries", [])],
                line=d.get("line"),
            )
        case "TryExcept":
            return TryExcept(
                try_body=[_dict_to_stmt(s) for s in d.get("try_body", [])],
                except_body=[_dict_to_stmt(s) for s in d.get("except_body", [])],
                metadata=(
                    [_dict_to_meta(m) for m in d["metadata"]]
                    if d.get("metadata")
                    else None
                ),
                line=d.get("line"),
            )
    return Assignment(target="_unknown", line=d.get("line"))


def _dict_to_expr(d: dict) -> Expression:
    t = d.get("type", "")
    match t:
        case "Identifier":
            return Identifier(name=d["name"], line=d.get("line"))
        case "Literal":
            return Literal(
                value=d.get("value"),
                literal_type=d.get("literal_type", "none"),
                line=d.get("line"),
            )
        case "KeywordArg":
            return KeywordArg(
                name=d["name"], value=_dict_to_expr(d["value"]), line=d.get("line")
            )
        case "LabelRef":
            return LabelRef(name=d["name"], line=d.get("line"))
        case "Wildcard":
            return Wildcard(line=d.get("line"))
    return Identifier(name="_unknown", line=d.get("line"))


def _dict_to_output(o):
    if isinstance(o, dict) and o.get("type") == "Wildcard":
        return Wildcard()
    if isinstance(o, str):
        return o
    return str(o)


def _dict_to_meta(d: dict) -> MetaAnnotation:
    return MetaAnnotation(data=d.get("data", {}))


def _dict_to_param(d: dict) -> Parameter:
    return Parameter(
        name=d["name"],
        default=_dict_to_expr(d["default"]) if d.get("default") else None,
    )


def _dict_to_type_expr(d: dict) -> TypeExpr:
    return TypeExpr(
        name=d.get("name", "Any"),
        is_optional=d.get("is_optional", False),
        union_of=(
            [_dict_to_type_expr(u) for u in d["union_of"]]
            if d.get("union_of")
            else None
        ),
    )


def _dict_to_typehint_entry(d: dict) -> TypeHintEntry:
    return TypeHintEntry(
        func_name=d["func_name"],
        input_types=[_dict_to_type_expr(t) for t in d.get("input_types", [])],
        output_types=[_dict_to_type_expr(t) for t in d.get("output_types", [])],
    )
