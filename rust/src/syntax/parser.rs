//! Parse KIR text into a `Program`: indenter pass, pest grammar, then a
//! bottom-up transform that raises the reference's syntax errors in the same
//! (post-order) order.

use num_bigint::BigInt;
use pest::iterators::Pair;
use pest::Parser;
use pest_derive::Parser;

use crate::errors::{KirError, Result};
use crate::syntax::ast::{
    Arg, Def, Directives, Expr, Import, Kind, OutParam, Param, Program, Stmt, TypeExpr, TypeHintEntry, Use,
};
use crate::syntax::indenter::{self, Marked};
use crate::syntax::strlit;
use crate::syntax::value::Value;

#[derive(Parser)]
#[grammar = "syntax/kir.pest"]
struct KirParser;

/// A transformed top-level or block item before `@meta` / `@hint` attach.
enum Item {
    Stmt(Box<Stmt>),
    Meta(Directives),
    Hint(Directives),
    Use(Use),
    Import(Import),
    Export(String),
    Mode(String),
}

enum Out {
    Name(Option<String>),
    Label(String),
    Case(Value, String),
    Default(String),
    Collect(Expr, String),
}

fn err(message: impl Into<String>) -> KirError {
    KirError::syntax(message, None, None)
}

struct Builder<'a> {
    marked: &'a Marked,
}

impl Builder<'_> {
    fn line(&self, p: &Pair<Rule>) -> usize {
        self.marked.line_col(p.as_span().start()).0
    }

    /// The value of a string literal, decoded from the source text under it.
    fn string(&self, p: &Pair<Rule>) -> Result<String> {
        let span = p.as_span();
        strlit::decode(self.marked.source_text(span.start(), span.end())).map_err(err)
    }

    // ------------------------------------------------------------ values
    fn literal(&self, p: Pair<Rule>) -> Result<Value> {
        Ok(match p.as_rule() {
            Rule::int => Value::Int(parse_int(p.as_str())),
            Rule::float => {
                let f: f64 = p.as_str().parse().map_err(|e| err(format!("bad float: {e}")))?;
                if !f.is_finite() {
                    let (line, col) = self.marked.line_col(p.as_span().start());
                    return Err(KirError::syntax("float literal out of range", Some(line), Some(col)));
                }
                Value::Float(f)
            }
            Rule::true_lit => Value::Bool(true),
            Rule::false_lit => Value::Bool(false),
            Rule::none_lit => Value::None,
            Rule::string => Value::Str(self.string(&p)?),
            Rule::list_lit => Value::List(p.into_inner().map(|i| self.literal(i)).collect::<Result<_>>()?),
            Rule::dict_lit => {
                let mut pairs = Vec::new();
                for dp in p.into_inner() {
                    let mut kv = dp.into_inner();
                    let k = self.literal(kv.next().expect("dict key"))?;
                    let v = self.literal(kv.next().expect("dict value"))?;
                    Value::dict_set(&mut pairs, k, v).map_err(err)?;
                }
                Value::Dict(pairs)
            }
            r => unreachable!("not a literal: {r:?}"),
        })
    }

    fn expr(&self, p: Pair<Rule>) -> Result<Expr> {
        match p.as_rule() {
            Rule::name => Ok(Expr::Name(p.as_str().to_string())),
            _ => Ok(Expr::Literal(self.literal(p)?)),
        }
    }

    /// A `@meta` / `@hint` value: names become strings.
    fn pair_value(&self, p: Pair<Rule>) -> Result<Value> {
        match p.as_rule() {
            Rule::name => Ok(Value::str(p.as_str())),
            Rule::tuple => Ok(Value::Tuple(p.into_inner().map(|i| self.pair_value(i)).collect::<Result<_>>()?)),
            _ => self.literal(p),
        }
    }

    fn directives(&self, p: Pair<Rule>) -> Result<Directives> {
        let mut d = Directives::new();
        for pair in p.into_inner() {
            let mut kv = pair.into_inner();
            let key = kv.next().expect("pair key").as_str().to_string();
            let value = self.pair_value(kv.next().expect("pair value"))?;
            d.insert(key, value);
        }
        Ok(d)
    }

    // ------------------------------------------------------------ types
    fn type_expr(&self, p: Pair<Rule>) -> TypeExpr {
        let mut parts: Vec<TypeExpr> = p.into_inner().map(|a| self.type_atom(a)).collect();
        if parts.len() == 1 {
            parts.pop().expect("one part")
        } else {
            TypeExpr::Union(parts)
        }
    }

    fn type_atom(&self, p: Pair<Rule>) -> TypeExpr {
        match p.as_rule() {
            Rule::type_any => return TypeExpr::Any,
            Rule::type_none => return TypeExpr::name("None"),
            _ => {}
        }
        let mut inner = p.into_inner();
        let name = func_name(inner.next().expect("type name"));
        let mut t = TypeExpr::Name(name.clone());
        for part in inner {
            match part.as_rule() {
                Rule::type_args => {
                    t = TypeExpr::Generic(name.clone(), part.into_inner().map(|a| self.type_expr(a)).collect())
                }
                _ => t = TypeExpr::Optional(Box::new(t)),
            }
        }
        t
    }

    fn type_list(&self, p: Pair<Rule>) -> Vec<TypeExpr> {
        p.into_inner().map(|t| self.type_expr(t)).collect()
    }

    // ------------------------------------------------------------ calls
    fn call(&self, p: Pair<Rule>) -> Result<Stmt> {
        let line = self.line(&p);
        let (mut ins, mut name, mut outs) = (Vec::new(), String::new(), Vec::new());
        for part in p.into_inner() {
            match part.as_rule() {
                Rule::in_list => {
                    for item in part.into_inner() {
                        let rule = item.as_rule();
                        let mut inner = item.into_inner();
                        ins.push(if rule == Rule::kwarg {
                            let key = inner.next().expect("key").as_str().to_string();
                            Arg { value: self.expr(inner.next().expect("value"))?, key: Some(key) }
                        } else {
                            Arg::pos(self.expr(inner.next().expect("value"))?)
                        });
                    }
                }
                Rule::func_name => name = func_name(part),
                Rule::out_list => {
                    for item in part.into_inner() {
                        outs.push(self.out_item(item)?);
                    }
                }
                r => unreachable!("call part {r:?}"),
            }
        }
        build_call(name, ins, outs, line)
    }

    fn out_item(&self, p: Pair<Rule>) -> Result<Out> {
        let rule = p.as_rule();
        let mut inner = p.into_inner();
        Ok(match rule {
            Rule::out_default => Out::Default(label_text(inner.next().expect("label"))),
            Rule::out_discard => Out::Name(None),
            Rule::out_label => Out::Label(label_text(inner.next().expect("label"))),
            Rule::out_name => Out::Name(Some(inner.next().expect("name").as_str().to_string())),
            Rule::out_collect => Out::Collect(
                self.expr(inner.next().expect("collected value"))?,
                inner.next().expect("collect target").as_str().to_string(),
            ),
            Rule::out_case => {
                let value = inner.next().expect("case value");
                let label = inner.next().expect("label");
                if value.as_rule() == Rule::name {
                    let (line, col) = self.marked.line_col(label.as_span().start());
                    return Err(KirError::syntax("switch cases must be literals", Some(line), Some(col)));
                }
                Out::Case(self.literal(value)?, label_text(label))
            }
            r => unreachable!("out item {r:?}"),
        })
    }

    // ------------------------------------------------------------ statements
    fn item(&self, p: Pair<Rule>) -> Result<Item> {
        Ok(match p.as_rule() {
            Rule::use_decl => {
                let mut inner = p.into_inner();
                let library = self.string(&inner.next().expect("library"))?;
                Item::Use(Use { library, alias: inner.next().map(|a| a.as_str().to_string()) })
            }
            Rule::import_decl => {
                let mut inner = p.into_inner();
                let module = self.string(&inner.next().expect("module"))?;
                let alias = inner.next().expect("alias").as_str().to_string();
                Item::Import(Import { module, alias })
            }
            Rule::export_decl => Item::Export(p.into_inner().next().expect("export").as_str().to_string()),
            Rule::meta => Item::Meta(self.directives(p)?),
            Rule::hint => Item::Hint(self.directives(p)?),
            Rule::mode => Item::Mode(p.into_inner().next().expect("mode").as_str().to_string()),
            _ => Item::Stmt(Box::new(self.statement(p)?)),
        })
    }

    fn statement(&self, p: Pair<Rule>) -> Result<Stmt> {
        let line = self.line(&p);
        Ok(match p.as_rule() {
            Rule::call => self.call(p)?,
            Rule::assignment => {
                let mut inner: Vec<Pair<Rule>> = p.into_inner().collect();
                let value = self.expr(inner.pop().expect("value"))?;
                let ty = if inner.len() == 2 { Some(self.type_expr(inner.pop().expect("type"))) } else { None };
                let target = inner.pop().expect("target").as_str().to_string();
                Stmt::new(Kind::Assign { target, value, ty }, Some(line))
            }
            Rule::namespace => {
                let mut inner = p.into_inner();
                let label = inner.next().expect("label").as_str().to_string();
                let body = self.body(inner)?;
                Stmt::new(Kind::Namespace { label, body }, Some(line))
            }
            Rule::dataflow => {
                let body = self.block(p.into_inner().next().expect("block"))?;
                Stmt::new(Kind::Dataflow { body }, Some(line))
            }
            Rule::try_block => {
                let mut inner = p.into_inner();
                let body = self.block(inner.next().expect("body"))?;
                let next = inner.next().expect("handler");
                let (error_name, handler) = if next.as_rule() == Rule::name {
                    (Some(next.as_str().to_string()), self.block(inner.next().expect("handler"))?)
                } else {
                    (None, self.block(next)?)
                };
                Stmt::new(Kind::Try { body, handler, error_name }, Some(line))
            }
            Rule::subgraph => self.subgraph(p, line)?,
            Rule::typehint_block => {
                let mut entries = Vec::new();
                for e in p.into_inner() {
                    let (mut ins, mut name, mut outs) = (Vec::new(), None, Vec::new());
                    for part in e.into_inner() {
                        match part.as_rule() {
                            Rule::func_name => name = Some(func_name(part)),
                            Rule::type_list if name.is_none() => ins = self.type_list(part),
                            _ => outs = self.type_list(part),
                        }
                    }
                    entries.push(TypeHintEntry { name: name.expect("entry name"), inputs: ins, outputs: outs });
                }
                Stmt::new(Kind::TypeHints { entries }, Some(line))
            }
            r => unreachable!("statement {r:?}"),
        })
    }

    fn subgraph(&self, p: Pair<Rule>, line: usize) -> Result<Stmt> {
        let (mut params, mut name, mut outputs, mut body) = (Vec::new(), None, Vec::new(), Vec::new());
        for part in p.into_inner() {
            match part.as_rule() {
                Rule::param_list => {
                    for param in part.into_inner() {
                        let mut inner = param.into_inner();
                        let pname = inner.next().expect("param name").as_str().to_string();
                        let (mut ty, mut default) = (None, None);
                        for r in inner {
                            if r.as_rule() == Rule::type_expr {
                                ty = Some(self.type_expr(r));
                            } else {
                                default = Some(self.expr(r)?);
                            }
                        }
                        params.push(Param { name: pname, ty, default });
                    }
                }
                Rule::name => name = Some(part.as_str().to_string()),
                Rule::def_outs => {
                    for o in part.into_inner() {
                        let mut inner = o.into_inner();
                        let oname = inner.next().expect("output name").as_str().to_string();
                        outputs.push(OutParam { name: oname, ty: inner.next().map(|t| self.type_expr(t)) });
                    }
                }
                Rule::block => body = self.block(part)?,
                r => unreachable!("def part {r:?}"),
            }
        }
        let name = name.expect("def name");
        Ok(Stmt::new(Kind::Def(Def { name, params, outputs, body }), Some(line)))
    }

    fn block(&self, p: Pair<Rule>) -> Result<Vec<Stmt>> {
        self.body(p.into_inner())
    }

    fn body<'i>(&self, pairs: impl Iterator<Item = Pair<'i, Rule>>) -> Result<Vec<Stmt>> {
        let items = pairs.map(|p| self.item(p)).collect::<Result<Vec<_>>>()?;
        attach(items)
    }
}

fn label_text(p: Pair<Rule>) -> String {
    let s = p.as_str();
    s[1..s.len() - 1].to_string()
}

fn func_name(p: Pair<Rule>) -> String {
    p.into_inner().map(|n| n.as_str()).collect::<Vec<_>>().join(".")
}

/// Python's `int(text, 0)`, falling back to base 10 for leading zeros.
fn parse_int(text: &str) -> BigInt {
    let (neg, digits) = match text.as_bytes()[0] {
        b'-' => (true, &text[1..]),
        b'+' => (false, &text[1..]),
        _ => (false, text),
    };
    let lower = digits.to_ascii_lowercase();
    let (radix, body) = match lower.get(..2) {
        Some("0x") => (16, &digits[2..]),
        Some("0o") => (8, &digits[2..]),
        Some("0b") => (2, &digits[2..]),
        _ => (10, digits),
    };
    let n = BigInt::parse_bytes(body.as_bytes(), radix).expect("grammar guarantees digits");
    if neg {
        -n
    } else {
        n
    }
}

fn labels(outs: Vec<Out>, line: usize) -> Result<Vec<String>> {
    outs.into_iter()
        .map(|o| match o {
            Out::Label(l) => Ok(l),
            _ => Err(KirError::syntax("expected only labels", Some(line), None)),
        })
        .collect()
}

fn build_call(name: String, ins: Vec<Arg>, outs: Vec<Out>, line: usize) -> Result<Stmt> {
    let at = |m: String| KirError::syntax(m, Some(line), None);
    let n = name.as_str();
    if matches!(n, "branch" | "switch" | "each" | "collect") && (ins.len() != 1 || ins[0].key.is_some()) {
        return Err(at(format!("{n} takes exactly one positional input")));
    }
    if matches!(n, "jump" | "parallel") && !ins.is_empty() {
        return Err(at(format!("{n} takes no inputs")));
    }
    let first = || ins[0].value.clone();
    let kind = match n {
        "branch" => {
            let l = labels(outs, line)?;
            if l.len() != 2 {
                return Err(at("branch needs two labels".into()));
            }
            let mut l = l.into_iter();
            Kind::Branch {
                cond: first(),
                true_label: l.next().expect("two labels"),
                false_label: l.next().expect("two labels"),
            }
        }
        "switch" => {
            let (mut cases, mut default) = (Vec::new(), None);
            for o in outs {
                match o {
                    Out::Case(v, l) => cases.push((v, l)),
                    Out::Default(l) if default.is_none() => default = Some(l),
                    _ => return Err(at("switch outputs are `value=>`label`` pairs".into())),
                }
            }
            Kind::Switch { value: first(), cases, default }
        }
        "jump" => {
            let mut l = labels(outs, line)?;
            if l.len() != 1 {
                return Err(at("jump needs one label".into()));
            }
            Kind::Jump { label: l.pop().expect("one label") }
        }
        "parallel" => {
            let l = labels(outs, line)?;
            if l.is_empty() {
                return Err(at("parallel needs at least one label".into()));
            }
            Kind::Parallel { labels: l }
        }
        "collect" => {
            if !(3..=4).contains(&outs.len())
                || !matches!(outs.last(), Some(Out::Collect(_, _)))
                || !matches!(&outs[outs.len() - 2], Out::Label(_))
                || !outs[..outs.len() - 2].iter().all(|o| matches!(o, Out::Name(_)))
            {
                return Err(at("collect outputs are item[, index], `label`, value -> target".into()));
            }
            let mut outs = outs;
            let Some(Out::Collect(value, target)) = outs.pop() else { unreachable!() };
            let Some(Out::Label(label)) = outs.pop() else { unreachable!() };
            let has_index = outs.len() == 2;
            let mut names = outs.into_iter().map(|o| match o {
                Out::Name(name) => name,
                _ => unreachable!(),
            });
            let item = names.next().expect("item");
            let index = names.next().flatten();
            Kind::Collect { items: first(), item, index, label, value, target, has_index }
        }
        "each" => {
            let shape_ok = matches!(outs.last(), Some(Out::Label(_)))
                && outs[..outs.len() - 1].iter().all(|o| matches!(o, Out::Name(_)));
            if !shape_ok {
                return Err(at("each outputs are item[, index], `label`".into()));
            }
            let mut outs = outs;
            let Some(Out::Label(label)) = outs.pop() else { unreachable!("checked") };
            let names: Vec<Option<String>> = outs
                .into_iter()
                .map(|o| match o {
                    Out::Name(n) => n,
                    _ => unreachable!("checked"),
                })
                .collect();
            if !(1..=2).contains(&names.len()) {
                return Err(at("each binds an item and optionally an index".into()));
            }
            let has_index = names.len() == 2;
            let mut names = names.into_iter();
            let item = names.next().expect("item");
            let index = names.next().flatten();
            Kind::Each { items: first(), item, index, label, has_index }
        }
        _ => {
            let mut out_names = Vec::with_capacity(outs.len());
            for o in outs {
                match o {
                    Out::Name(n) => out_names.push(n),
                    _ => {
                        return Err(at(format!("node {} outputs must be names or _", crate::util::pyfmt::str_repr(n))))
                    }
                }
            }
            let mut seen_kw = false;
            for a in &ins {
                if a.key.is_some() {
                    seen_kw = true;
                } else if seen_kw {
                    return Err(at("positional input after keyword input".into()));
                }
            }
            Kind::Call { name: name.clone(), args: ins, outs: out_names }
        }
    };
    Ok(Stmt::new(kind, Some(line)))
}

/// Attach `@meta` / `@hint` to the statement that follows them.
fn attach(items: Vec<Item>) -> Result<Vec<Stmt>> {
    let mut out = Vec::new();
    let (mut meta, mut hint) = (Directives::new(), Directives::new());
    for item in items {
        match item {
            Item::Meta(m) => meta.extend(m),
            Item::Hint(h) => hint.extend(h),
            Item::Stmt(mut s) => {
                meta.extend(std::mem::take(&mut s.meta));
                hint.extend(std::mem::take(&mut s.hint));
                s.meta = std::mem::take(&mut meta);
                s.hint = std::mem::take(&mut hint);
                out.push(*s);
            }
            Item::Use(_) => return Err(err("@use is only allowed at the top of a file")),
            Item::Import(_) => return Err(err("@import is only allowed at the top of a file")),
            Item::Export(_) => return Err(err("@export is only allowed at the top of a file")),
            Item::Mode(_) => return Err(err("@mode is only allowed at the top of a file")),
        }
    }
    if !meta.is_empty() || !hint.is_empty() {
        return Err(err("@meta / @hint must be followed by a statement"));
    }
    Ok(out)
}

/// The offset of the first code line's indentation, when that line is indented:
/// `(?:[\t ]*(?:#[^\r\n]*)?\r?\n)*([\t ]*)` with a non-empty group not at the end.
fn first_code_indent(text: &str) -> Option<usize> {
    let b = text.as_bytes();
    let ws = |mut i: usize| {
        while matches!(b.get(i), Some(b' ' | b'\t')) {
            i += 1;
        }
        i
    };
    let mut pos = 0;
    loop {
        let mut i = ws(pos);
        if b.get(i) == Some(&b'#') {
            while !matches!(b.get(i), None | Some(b'\r' | b'\n')) {
                i += 1;
            }
        }
        if b.get(i) == Some(&b'\r') {
            i += 1;
        }
        if b.get(i) != Some(&b'\n') {
            break;
        }
        pos = i + 1;
    }
    let end = ws(pos);
    (end > pos && end < b.len()).then_some(pos)
}

/// Whether a token the grammar tried is identifier characters or a sign: pest
/// shows a literal as itself and a character range as `a..z`.
fn word_char(t: &impl std::fmt::Display) -> bool {
    let word = |c: char| c.is_ascii_alphanumeric() || matches!(c, '_' | '+' | '-');
    let text = t.to_string();
    let chars: Vec<char> = text.chars().collect();
    match chars.as_slice() {
        [a, '.', '.', b] => word(*a) && word(*b),
        _ => !chars.is_empty() && chars.iter().all(|&c| word(c)),
    }
}

/// Parse KIR source text. Line endings are `\n`, `\r\n` or a lone `\r`, as in Python.
pub fn parse(source: &str) -> Result<Program> {
    let mut text = source.replace("\r\n", "\n").replace('\r', "\n");
    if !text.ends_with('\n') {
        text.push('\n');
    }
    if let Some(at) = first_code_indent(&text) {
        let line = text[..at].matches('\n').count() + 1;
        return Err(KirError::syntax("unexpected indent", Some(line), Some(1)));
    }
    let mut marked = indenter::mark(&text);
    pest::set_error_detail(true);
    let file = match KirParser::parse(Rule::file, &marked.text) {
        Ok(mut pairs) => match marked.stop.take() {
            Some(stop) => return Err(stop),
            None => pairs.next().expect("file rule"),
        },
        Err(e) => {
            // Only identifier characters (or an exponent sign) expected at the
            // furthest point: a word-boundary check just past a word failed.
            let (at, probe) = match e.parse_attempts() {
                Some(a) => {
                    (a.max_position, !a.expected_tokens().is_empty() && a.expected_tokens().iter().all(word_char))
                }
                None => match e.location {
                    pest::error::InputLocation::Pos(p) | pest::error::InputLocation::Span((p, _)) => (p, false),
                },
            };
            return Err(match marked.grammar_error(at, probe) {
                Some((line, col)) => KirError::syntax("unexpected input", Some(line), Some(col)),
                None => marked.stop.take().expect("a stopped indentation pass"),
            });
        }
    };
    let b = Builder { marked: &marked };
    let items =
        file.into_inner().filter(|p| p.as_rule() != Rule::EOI).map(|p| b.item(p)).collect::<Result<Vec<_>>>()?;
    let mut program = Program::default();
    let mut rest = items.into_iter().peekable();
    while let Some(Item::Use(_) | Item::Import(_) | Item::Export(_) | Item::Mode(_)) = rest.peek() {
        match rest.next() {
            Some(Item::Use(u)) => program.uses.push(u),
            Some(Item::Import(i)) => program.imports.push(i),
            Some(Item::Export(e)) => program.exports.push(e),
            Some(Item::Mode(m)) => program.mode = Some(m),
            _ => unreachable!("peeked"),
        }
    }
    program.body = attach(rest.collect())?;
    Ok(program)
}
