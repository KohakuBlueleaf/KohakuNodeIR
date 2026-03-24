"""Lark Transformer: converts Lark parse trees into KohakuNodeIR AST nodes."""

import ast as _ast_stdlib

import lark

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
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
    Wildcard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_line(obj: object) -> int | None:
    """Return the source line number from a Lark Tree or Token, or None."""
    if isinstance(obj, lark.Tree):
        meta = getattr(obj, "meta", None)
        if meta is not None:
            return getattr(meta, "line", None)
        return None
    if isinstance(obj, lark.Token):
        return getattr(obj, "line", None)
    return None


def _attach_meta(
    stmt: Statement,
    pending: list[MetaAnnotation],
) -> None:
    """Attach accumulated @meta annotations to a statement that supports them."""
    if not pending:
        return
    if hasattr(stmt, "metadata"):
        stmt.metadata = list(pending)
    pending.clear()


def _process_body(
    raw_children: list,
) -> list[Statement]:
    """Walk a flat list of statements, attaching @meta annotations to the next
    eligible statement and discarding None values."""
    result: list[Statement] = []
    pending_meta: list[MetaAnnotation] = []

    for item in raw_children:
        if item is None:
            continue
        if isinstance(item, MetaAnnotation):
            pending_meta.append(item)
            continue
        if isinstance(item, Statement):
            if pending_meta:
                _attach_meta(item, pending_meta)
            result.append(item)
        # Anything else (should not appear) is silently ignored.

    return result


# ---------------------------------------------------------------------------
# Builtin call dispatch helpers
# ---------------------------------------------------------------------------


def _make_branch(inputs: list, outputs: list, line: int | None) -> Branch:
    condition = inputs[0] if inputs else Identifier()
    label_refs = [o for o in outputs if isinstance(o, LabelRef)]
    true_label = label_refs[0].name if len(label_refs) >= 1 else ""
    false_label = label_refs[1].name if len(label_refs) >= 2 else ""
    return Branch(
        condition=condition, true_label=true_label, false_label=false_label, line=line
    )


def _make_switch(inputs: list, outputs: list, line: int | None) -> Switch:
    value = inputs[0] if inputs else Identifier()
    cases: list[tuple] = []
    default_label: str | None = None
    for item in outputs:
        if isinstance(item, tuple):
            key, label_name = item
            if key == "_default_":
                default_label = label_name
            else:
                cases.append((key, label_name))
    return Switch(value=value, cases=cases, default_label=default_label, line=line)


def _make_jump(outputs: list, line: int | None) -> Jump:
    label_refs = [o for o in outputs if isinstance(o, LabelRef)]
    target = label_refs[0].name if label_refs else ""
    return Jump(target=target, line=line)


def _make_parallel(outputs: list, line: int | None) -> Parallel:
    label_refs = [o for o in outputs if isinstance(o, LabelRef)]
    return Parallel(labels=[lr.name for lr in label_refs], line=line)


def _parse_subgraph_children(
    children: list,
) -> tuple[list[Parameter], list[str], list, lark.Token | None]:
    """Extract (params, output_names, body_stmts, name_token) from subgraph_def children."""
    params: list[Parameter] = []
    output_names: list[str] = []
    body_stmts: list = []
    name_tokens: list[lark.Token] = []

    for child in children:
        if isinstance(child, lark.Token):
            name_tokens.append(child)
        elif isinstance(child, list):
            if child and isinstance(child[0], Parameter):
                params = child
            elif child and isinstance(child[0], str):
                output_names = child
        elif isinstance(child, Statement):
            body_stmts.append(child)

    bracket_values = {"(", ")", "[", "]", "{", "}"}
    real_tokens = [t for t in name_tokens if str(t) not in bracket_values]
    name_token = real_tokens[0] if real_tokens else None
    return params, output_names, body_stmts, name_token


# ---------------------------------------------------------------------------
# Transformer
# ---------------------------------------------------------------------------


class KirTransformer(lark.Transformer):
    """Transform a Lark parse tree produced by the KIR grammar into AST nodes."""

    # ------------------------------------------------------------------ #
    # Literals                                                             #
    # ------------------------------------------------------------------ #

    def int_lit(self, children: list) -> Literal:
        token = children[0]
        line = _get_line(token)
        raw = str(token)
        # int() handles all bases automatically (0x, 0o, 0b, and plain decimal).
        value = int(raw, 0)
        return Literal(value=value, literal_type="int", line=line)

    def float_lit(self, children: list) -> Literal:
        token = children[0]
        line = _get_line(token)
        value = float(str(token))
        return Literal(value=value, literal_type="float", line=line)

    def bool_lit(self, children: list) -> Literal:
        token = children[0]
        line = _get_line(token)
        value = str(token) == "True"
        return Literal(value=value, literal_type="bool", line=line)

    def none_lit(self, children: list) -> Literal:
        token = children[0]
        line = _get_line(token)
        return Literal(value=None, literal_type="none", line=line)

    def string_lit(self, children: list) -> Literal:
        token = children[0]
        line = _get_line(token)
        # ast.literal_eval strips quotes and resolves escape sequences.
        value = _ast_stdlib.literal_eval(str(token))
        return Literal(value=value, literal_type="str", line=line)

    def list_lit(self, children: list) -> Literal:
        # children may contain LSQB / RSQB bracket tokens — filter them out.
        # Extract raw Python values from Literal children.
        exprs = [c for c in children if not isinstance(c, lark.Token)]
        line = _get_line(children[0]) if children else None
        value = [e.value if isinstance(e, Literal) else e for e in exprs]
        return Literal(value=value, literal_type="list", line=line)

    def dict_lit(self, children: list) -> Literal:
        # children are either bracket Tokens or tuple pairs from dict_pair.
        # We extract the raw Python values from Literal keys/values to build
        # a real dict for the AST node's value field.
        pairs = [c for c in children if isinstance(c, tuple)]
        line = _get_line(children[0]) if children else None
        value = {}
        for k, v in pairs:
            # Extract raw Python values for dict construction.
            key = k.value if isinstance(k, Literal) else k
            val = v.value if isinstance(v, Literal) else v
            value[key] = val
        return Literal(value=value, literal_type="dict", line=line)

    def dict_pair(self, children: list) -> tuple:
        key, val = children[0], children[1]
        return (key, val)

    # ------------------------------------------------------------------ #
    # Identifier                                                           #
    # ------------------------------------------------------------------ #

    def identifier(self, children: list) -> Identifier:
        token = children[0]
        line = _get_line(token)
        return Identifier(name=str(token), line=line)

    # ------------------------------------------------------------------ #
    # Label reference                                                      #
    # ------------------------------------------------------------------ #

    def label_ref(self, children: list) -> LabelRef:
        token = children[0]
        line = _get_line(token)
        # Strip surrounding backticks.
        name = str(token).strip("`")
        return LabelRef(name=name, line=line)

    # ------------------------------------------------------------------ #
    # Call statement components                                            #
    # ------------------------------------------------------------------ #

    def func_name(self, children: list) -> str:
        return ".".join(str(c) for c in children)

    def call_in_list(self, children: list) -> list:
        return list(children)

    def pos_arg(self, children: list):
        return children[0]

    def kwarg(self, children: list) -> KeywordArg:
        name_token = children[0]
        value = children[1]
        line = _get_line(name_token)
        return KeywordArg(name=str(name_token), value=value, line=line)

    def call_out_list(self, children: list) -> list:
        return list(children)

    def out_name(self, children: list) -> str:
        return str(children[0])

    def out_wildcard(self, children: list) -> Wildcard:
        token = children[0]
        line = _get_line(token)
        return Wildcard(line=line)

    def out_label_ref(self, children: list) -> LabelRef:
        # children[0] is already a LabelRef from label_ref rule.
        return children[0]

    def out_switch_case(self, children: list) -> tuple:
        # (expr, LabelRef) → store label name as string
        expr = children[0]
        label_ref: LabelRef = children[1]
        return (expr, label_ref.name)

    def out_switch_default(self, children: list) -> tuple:
        # WILDCARD "=>" label_ref → mark with sentinel key
        label_ref: LabelRef = children[-1]
        return ("_default_", label_ref.name)

    # ------------------------------------------------------------------ #
    # Unified call statement → dispatch to correct AST node               #
    # ------------------------------------------------------------------ #

    def call_stmt(self, children: list) -> Statement:
        # Grammar: LPAR call_in_list? RPAR func_name LPAR call_out_list? RPAR
        # LPAR/RPAR appear as named Tokens; we scan children by type.
        tokens = [c for c in children if isinstance(c, lark.Token)]
        non_tokens = [c for c in children if not isinstance(c, lark.Token)]

        fn: str = next((x for x in non_tokens if isinstance(x, str)), "")
        fn_index = next(i for i, x in enumerate(non_tokens) if isinstance(x, str))

        inputs: list = []
        outputs: list = []
        for i, item in enumerate(non_tokens):
            if isinstance(item, list):
                if i < fn_index:
                    inputs = item
                else:
                    outputs = item

        line: int | None = _get_line(tokens[0]) if tokens else None

        if fn == "branch":
            return _make_branch(inputs, outputs, line)
        if fn == "switch":
            return _make_switch(inputs, outputs, line)
        if fn == "jump":
            return _make_jump(outputs, line)
        if fn == "parallel":
            return _make_parallel(outputs, line)
        return FuncCall(inputs=inputs, func_name=fn, outputs=outputs, line=line)

    # ------------------------------------------------------------------ #
    # Meta annotation                                                      #
    # ------------------------------------------------------------------ #

    def meta_pair(self, children: list) -> tuple:
        key_token = children[0]
        value = children[1]
        # Extract raw Python value from Literal/Identifier for metadata storage.
        if isinstance(value, Literal):
            value = value.value
        elif isinstance(value, Identifier):
            value = value.name
        return (str(key_token), value)

    def meta_tuple(self, children: list) -> tuple:
        # children are already-transformed meta_val items (Tokens filtered out).
        # Extract raw values for tuple storage.
        values = []
        for c in children:
            if isinstance(c, lark.Token):
                continue
            if isinstance(c, Literal):
                values.append(c.value)
            elif isinstance(c, Identifier):
                values.append(c.name)
            else:
                values.append(c)
        return tuple(values)

    def meta_anno(self, children: list) -> MetaAnnotation:
        # children is a list of (key, value) tuples from meta_pair.
        line: int | None = None
        data: dict = {}
        for item in children:
            if isinstance(item, tuple):
                k, v = item
                data[k] = v
            elif isinstance(item, lark.Token) and line is None:
                line = _get_line(item)
        return MetaAnnotation(data=data, line=line)

    # ------------------------------------------------------------------ #
    # Assignment                                                           #
    # ------------------------------------------------------------------ #

    def assignment(self, children: list) -> Assignment:
        name_token = children[0]
        value = children[1]
        line = _get_line(name_token)
        return Assignment(target=str(name_token), value=value, line=line)

    # ------------------------------------------------------------------ #
    # Mode declaration                                                     #
    # ------------------------------------------------------------------ #

    def mode_decl(self, children: list) -> ModeDecl:
        mode_token = children[0]
        line = _get_line(mode_token)
        return ModeDecl(mode=str(mode_token), line=line)

    # ------------------------------------------------------------------ #
    # Namespace                                                            #
    # ------------------------------------------------------------------ #

    def namespace_body(self, children: list) -> Namespace:
        # children[0] = NAME token, rest = statements (after filtering).
        name_token = children[0]
        line = _get_line(name_token)
        raw_body = [c for c in children[1:] if not isinstance(c, lark.Token)]
        body = _process_body(raw_body)
        return Namespace(name=str(name_token), body=body, line=line)

    def namespace_empty(self, children: list) -> Namespace:
        name_token = children[0]
        line = _get_line(name_token)
        return Namespace(name=str(name_token), body=[], line=line)

    # ------------------------------------------------------------------ #
    # Subgraph definition                                                  #
    # ------------------------------------------------------------------ #

    def param_plain(self, children: list) -> Parameter:
        name_token = children[0]
        line = _get_line(name_token)
        return Parameter(name=str(name_token), line=line)

    def param_with_default(self, children: list) -> Parameter:
        name_token = children[0]
        default = children[1]
        line = _get_line(name_token)
        return Parameter(name=str(name_token), default=default, line=line)

    def param_list(self, children: list) -> list:
        return [c for c in children if isinstance(c, Parameter)]

    def def_output_list(self, children: list) -> list:
        return [str(c) for c in children if isinstance(c, lark.Token)]

    def subgraph_def(self, children: list) -> SubgraphDef:
        # Grammar: "@def" LPAR param_list? RPAR NAME LPAR def_output_list? RPAR
        #          ":" _NEWLINE _INDENT statements+ _DEDENT
        params, output_names, body_stmts, name_token = _parse_subgraph_children(
            children
        )
        name_str = str(name_token) if name_token else ""
        line = _get_line(name_token) if name_token else None
        body = _process_body(body_stmts)
        return SubgraphDef(
            name=name_str,
            params=params,
            outputs=output_names,
            body=body,
            line=line,
        )

    # ------------------------------------------------------------------ #
    # Dataflow block                                                      #
    # ------------------------------------------------------------------ #

    def dataflow_block(self, children: list) -> DataflowBlock:
        raw_body = [c for c in children if not isinstance(c, lark.Token)]
        body = _process_body(raw_body)
        line = _get_line(children[0]) if children else None
        return DataflowBlock(body=body, line=line)

    # ------------------------------------------------------------------ #
    # Statement / compound_stmt pass-through                              #
    # ------------------------------------------------------------------ #

    def statement(self, children: list):
        # Returns the single meaningful child (simple_stmt or compound_stmt result).
        for child in children:
            if child is not None and not isinstance(child, lark.Token):
                return child
        return None

    def simple_stmt(self, children: list):
        return children[0] if children else None

    def compound_stmt(self, children: list):
        return children[0] if children else None

    # ------------------------------------------------------------------ #
    # Program root                                                         #
    # ------------------------------------------------------------------ #

    def start(self, children: list) -> Program:
        # Extract ModeDecl if present; pass the rest through _process_body.
        mode: str | None = None
        raw_stmts: list = []

        for child in children:
            if child is None or isinstance(child, lark.Token):
                continue
            if isinstance(child, ModeDecl):
                mode = child.mode
            else:
                raw_stmts.append(child)

        body = _process_body(raw_stmts)
        return Program(body=body, mode=mode)
