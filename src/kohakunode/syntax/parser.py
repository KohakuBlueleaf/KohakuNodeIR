"""Parse KIR text into a :class:`Program`."""

import ast as pyast
import math
import re
from functools import lru_cache
from pathlib import Path

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedInput, VisitError
from lark.indenter import DedentError, Indenter

from kohakunode.errors import KirSyntaxError
from kohakunode.syntax.ast import (
    ANY,
    Arg,
    Assign,
    Branch,
    Call,
    Dataflow,
    Def,
    Each,
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
    TypeExpr,
    TypeHintEntry,
    TypeHints,
    Use,
)

GRAMMAR = Path(__file__).with_name("kir.lark")


class _KirIndenter(Indenter):
    NL_type = "_NEWLINE"
    OPEN_PAREN_types = ["LPAR", "LSQB", "LBRACE"]
    CLOSE_PAREN_types = ["RPAR", "RSQB", "RBRACE"]
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 4

    def handle_NL(self, token):
        try:
            yield from super().handle_NL(token)
        except DedentError:
            indent = token.rsplit("\n", 1)[1].expandtabs(self.tab_len)
            raise KirSyntaxError(
                "unindent does not match any outer indentation level",
                token.end_line,
                len(indent) + 1,
            ) from None


@lru_cache(maxsize=1)
def _lark() -> Lark:
    return Lark(
        GRAMMAR.read_text(encoding="utf-8"),
        parser="lalr",
        lexer="contextual",
        postlex=_KirIndenter(),
        propagate_positions=True,
        maybe_placeholders=False,
    )


def _int(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 10)


# Markers for directives that attach to the next statement.
class _Meta(dict):
    pass


class _Hint(dict):
    pass


class _Mode(str):
    pass


@v_args(inline=True)
class _ToAst(Transformer):
    # ---------------------------------------------------------- values
    def int_lit(self, tok):
        return Literal(_int(str(tok)))

    def float_lit(self, tok):
        value = float(tok)
        if not math.isfinite(value):
            raise KirSyntaxError("float literal out of range", tok.line, tok.column)
        return Literal(value)

    def true_lit(self, _):
        return Literal(True)

    def false_lit(self, _):
        return Literal(False)

    def none_lit(self, _):
        return Literal(None)

    def string_lit(self, tok):
        return Literal(pyast.literal_eval(str(tok)))

    def list_lit(self, *items):
        return Literal([i.value for i in items])

    def dict_lit(self, *pairs):
        return Literal({k.value: v.value for k, v in pairs})

    def dict_pair(self, k, v):
        return (k, v)

    def name(self, tok):
        return Name(str(tok))

    def tuple(self, *items):
        return Literal(tuple(i.value if isinstance(i, Literal) else i.id for i in items))

    # ---------------------------------------------------------- types
    def type_any(self, _):
        return ANY

    def type_name(self, tok):
        return TypeExpr("name", str(tok))

    def type_none(self, _):
        return TypeExpr("name", "None")

    def type_optional(self, tok):
        return TypeExpr("optional", "", (TypeExpr("name", str(tok)),))

    def type_generic(self, tok, *args):
        return TypeExpr("generic", str(tok), tuple(args))

    def type_generic_optional(self, tok, *args):
        return TypeExpr("optional", "", (TypeExpr("generic", str(tok), tuple(args)),))

    def type_union(self, *parts):
        return TypeExpr("union", "", tuple(parts))

    def type_list(self, *types):
        return list(types)

    # ---------------------------------------------------------- directives
    def pair(self, key, value):
        if isinstance(value, Name):
            value = value.id
        elif isinstance(value, Literal):
            value = value.value
        return (str(key), value)

    def pair_name(self, tok):
        return Name(str(tok))

    def meta(self, *pairs):
        return _Meta(pairs)

    def hint(self, *pairs):
        return _Hint(pairs)

    def mode(self, tok):
        return _Mode(str(tok))

    def use_decl(self, lib, alias=None):
        return Use(pyast.literal_eval(str(lib)), str(alias) if alias is not None else None)

    # ---------------------------------------------------------- calls
    def func_name(self, *parts):
        return ".".join(str(p) for p in parts)

    def in_list(self, *items):
        return list(items)

    def kwarg(self, key, value):
        return Arg(value, str(key))

    def posarg(self, value):
        return Arg(value)

    def out_list(self, *items):
        return list(items)

    def out_name(self, tok):
        return ("name", str(tok))

    def out_discard(self, _):
        return ("name", None)

    def out_label(self, tok):
        return ("label", str(tok)[1:-1])

    def out_case(self, value, tok):
        if not isinstance(value, Literal):
            raise KirSyntaxError("switch cases must be literals", tok.line, tok.column)
        return ("case", value.value, str(tok)[1:-1])

    def out_default(self, _, tok):
        return ("default", str(tok)[1:-1])

    @v_args(meta=True, inline=True)
    def call(self, meta, *parts):
        ins, name, outs = [], None, []
        for p in parts:
            if isinstance(p, str) and name is None:
                name = p
            elif name is None:
                ins = p
            else:
                outs = p
        return _build_call(name, ins, outs, meta.line)

    @v_args(meta=True, inline=True)
    def assignment(self, meta, target, *rest):
        type_ = rest[0] if len(rest) == 2 else None
        return Assign(str(target), rest[-1], type_, line=meta.line)

    # ---------------------------------------------------------- compound
    def block(self, *items):
        return _attach(list(items))

    @v_args(meta=True, inline=True)
    def namespace_body(self, meta, label, *items):
        return Namespace(str(label), _attach(list(items)), line=meta.line)

    @v_args(meta=True, inline=True)
    def namespace_empty(self, meta, label):
        return Namespace(str(label), [], line=meta.line)

    @v_args(meta=True, inline=True)
    def dataflow(self, meta, body):
        return Dataflow(body, line=meta.line)

    @v_args(meta=True, inline=True)
    def try_block(self, meta, body, *rest):
        error_name = str(rest[0]) if len(rest) == 2 else None
        return Try(body, rest[-1], error_name, line=meta.line)

    def param_list(self, *params):
        return list(params)

    def param(self, name, *rest):
        type_, default = None, None
        for r in rest:
            if isinstance(r, TypeExpr):
                type_ = r
            else:
                default = r
        return Param(str(name), type_, default)

    def def_outs(self, *outs):
        return list(outs)

    def def_out(self, name, type_=None):
        return OutParam(str(name), type_)

    @v_args(meta=True, inline=True)
    def subgraph(self, meta, *parts):
        params, outputs, name, body = [], [], None, parts[-1]
        for p in parts[:-1]:
            if isinstance(p, Token):
                name = str(p)
            elif name is None:
                params = p
            else:
                outputs = p
        return Def(name, params, outputs, body, line=meta.line)

    def typehint_entry(self, *parts):
        ins, name, outs = [], None, []
        for p in parts:
            if isinstance(p, str) and name is None:
                name = p
            elif name is None:
                ins = p
            else:
                outs = p
        return TypeHintEntry(name, tuple(ins), tuple(outs))

    @v_args(meta=True, inline=True)
    def typehint_block(self, meta, *entries):
        return TypeHints([e for e in entries if isinstance(e, TypeHintEntry)], line=meta.line)

    def start(self, *items):
        return list(items)


def _labels(outs, line):
    if any(kind != "label" for kind, *_ in outs):
        raise KirSyntaxError("expected only labels", line)
    return [o[1] for o in outs]


def _build_call(name: str, ins: list[Arg], outs: list[tuple], line: int) -> Stmt:
    positional = [a for a in ins if a.key is None]
    if name in ("branch", "switch", "each") and (len(ins) != 1 or ins[0].key is not None):
        raise KirSyntaxError(f"{name} takes exactly one positional input", line)
    if name in ("jump", "parallel") and ins:
        raise KirSyntaxError(f"{name} takes no inputs", line)
    match name:
        case "branch":
            labels = _labels(outs, line)
            if len(labels) != 2:
                raise KirSyntaxError("branch needs two labels", line)
            return Branch(positional[0].value, labels[0], labels[1], line=line)
        case "switch":
            cases, default = [], None
            for o in outs:
                if o[0] == "case":
                    cases.append((o[1], o[2]))
                elif o[0] == "default" and default is None:
                    default = o[1]
                else:
                    raise KirSyntaxError("switch outputs are `value=>`label`` pairs", line)
            return Switch(positional[0].value, cases, default, line=line)
        case "jump":
            labels = _labels(outs, line)
            if len(labels) != 1:
                raise KirSyntaxError("jump needs one label", line)
            return Jump(labels[0], line=line)
        case "parallel":
            labels = _labels(outs, line)
            if not labels:
                raise KirSyntaxError("parallel needs at least one label", line)
            return Parallel(labels, line=line)
        case "each":
            if not outs or outs[-1][0] != "label" or any(o[0] != "name" for o in outs[:-1]):
                raise KirSyntaxError("each outputs are item[, index], `label`", line)
            names = [o[1] for o in outs[:-1]]
            if len(names) not in (1, 2):
                raise KirSyntaxError("each binds an item and optionally an index", line)
            index = names[1] if len(names) == 2 else None
            return Each(
                positional[0].value, names[0], index, outs[-1][1], len(names) == 2, line=line
            )
    if any(o[0] != "name" for o in outs):
        raise KirSyntaxError(f"node {name!r} outputs must be names or _", line)
    seen_kw = False
    for a in ins:
        if a.key is not None:
            seen_kw = True
        elif seen_kw:
            raise KirSyntaxError("positional input after keyword input", line)
    return Call(name, ins, [o[1] for o in outs], line=line)


def _attach(items: list) -> list[Stmt]:
    """Attach `@meta` / `@hint` to the statement that follows them."""
    out: list[Stmt] = []
    meta: dict = {}
    hint: dict = {}
    for item in items:
        if isinstance(item, _Meta):
            meta.update(item)
        elif isinstance(item, _Hint):
            hint.update(item)
        elif isinstance(item, Stmt):
            item.meta = meta | item.meta
            item.hint = hint | item.hint
            meta, hint = {}, {}
            out.append(item)
        elif isinstance(item, (Use, _Mode)):
            raise KirSyntaxError(f"{_directive(item)} is only allowed at the top of a file")
    if meta or hint:
        raise KirSyntaxError("@meta / @hint must be followed by a statement")
    return out


def _directive(item) -> str:
    return "@use" if isinstance(item, Use) else "@mode"


_FIRST_CODE = re.compile(r"(?:[\t ]*(?:#[^\r\n]*)?\r?\n)*([\t ]*)")


def parse(source: str) -> Program:
    """Parse KIR source text. Line endings are \\n, \\r\\n or a lone \\r, as in Python."""
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    if not source.endswith("\n"):
        source += "\n"
    lead = _FIRST_CODE.match(source)
    if lead.group(1) and lead.end() < len(source):
        line = source.count("\n", 0, lead.start(1)) + 1
        raise KirSyntaxError("unexpected indent", line, 1)
    try:
        tree = _lark().parse(source)
        items = _ToAst().transform(tree)
    except UnexpectedInput as exc:
        raise KirSyntaxError(
            f"unexpected input: {exc.get_context(source).strip()}", exc.line, exc.column
        ) from None
    except VisitError as exc:
        if isinstance(exc.orig_exc, KirSyntaxError):
            raise exc.orig_exc from None
        raise KirSyntaxError(str(exc.orig_exc)) from None
    program = Program()
    i = 0
    while i < len(items) and isinstance(items[i], (Use, _Mode)):
        if isinstance(items[i], Use):
            program.uses.append(items[i])
        else:
            program.mode = str(items[i])
        i += 1
    program.body = _attach(items[i:])
    return program


def parse_file(path: str | Path) -> Program:
    return parse(Path(path).read_text(encoding="utf-8"))
