//! Print a `Program` as canonical KIR text.
//!
//! Canonical form: 4-space indentation, one space after commas, `@meta` and
//! `@hint` each on one line before their statement, blank lines only around
//! top-level `@def` and `@typehint` blocks.

use crate::errors::{KirError, Result};
use crate::syntax::ast::{Arg, Directives, Expr, Kind, Program, Stmt, TypeExpr};
use crate::syntax::value::Value;
use crate::util::pyfmt::{float_repr, json_str};

const INDENT: &str = "    ";

pub fn write_literal(value: &Value) -> Result<String> {
    Ok(match value {
        Value::None => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Int(n) => n.to_string(),
        Value::Float(f) if !f.is_finite() => {
            return Err(KirError::Value(format!("{} has no KIR literal", float_repr(*f))))
        }
        Value::Float(f) => float_repr(*f),
        Value::Str(s) => json_str(s),
        Value::Tuple(items) if items.len() == 1 => format!("({},)", write_literal(&items[0])?),
        Value::Tuple(items) => format!("({})", join(items)?),
        Value::List(items) => format!("[{}]", join(items)?),
        Value::Dict(pairs) => {
            let mut parts = Vec::with_capacity(pairs.len());
            for (k, v) in pairs {
                parts.push(format!("{}: {}", write_literal(k)?, write_literal(v)?));
            }
            format!("{{{}}}", parts.join(", "))
        }
    })
}

fn join(items: &[Value]) -> Result<String> {
    Ok(items.iter().map(write_literal).collect::<Result<Vec<_>>>()?.join(", "))
}

pub fn write_expr(e: &Expr) -> Result<String> {
    match e {
        Expr::Name(n) => Ok(n.clone()),
        Expr::Literal(v) => write_literal(v),
    }
}

pub fn write_type(t: &TypeExpr) -> String {
    match t {
        TypeExpr::Any => "_".to_string(),
        TypeExpr::Name(n) => n.clone(),
        TypeExpr::Optional(inner) => write_type(inner) + "?",
        TypeExpr::Generic(n, args) => {
            format!("{n}[{}]", args.iter().map(write_type).collect::<Vec<_>>().join(", "))
        }
        TypeExpr::Union(parts) => parts.iter().map(write_type).collect::<Vec<_>>().join(" | "),
    }
}

fn arg(a: &Arg) -> Result<String> {
    let v = write_expr(&a.value)?;
    Ok(match &a.key {
        None => v,
        Some(k) => format!("{k}={v}"),
    })
}

fn pairs(d: &Directives) -> Result<String> {
    let mut parts = Vec::with_capacity(d.len());
    for (k, v) in d {
        parts.push(format!("{k}={}", write_literal(v)?));
    }
    Ok(parts.join(" "))
}

fn call_head(ins: &[String], name: &str, outs: &[String]) -> String {
    format!("({}){name}({})", ins.join(", "), outs.join(", "))
}

fn label(l: &str) -> String {
    format!("`{l}`")
}

/// The one-line text of a simple or builtin statement.
pub fn write_statement(s: &Stmt) -> Result<String> {
    Ok(match &s.kind {
        Kind::Assign { target, value, ty } => {
            let t = ty.as_ref().map_or(String::new(), |t| format!(": {}", write_type(t)));
            format!("{target}{t} = {}", write_expr(value)?)
        }
        Kind::Call { name, args, outs } => {
            let ins = args.iter().map(arg).collect::<Result<Vec<_>>>()?;
            let outs: Vec<String> = outs.iter().map(|o| o.clone().unwrap_or_else(|| "_".into())).collect();
            call_head(&ins, name, &outs)
        }
        Kind::Branch { cond, true_label, false_label } => {
            call_head(&[write_expr(cond)?], "branch", &[label(true_label), label(false_label)])
        }
        Kind::Switch { value, cases, default } => {
            let mut outs = Vec::with_capacity(cases.len() + 1);
            for (v, l) in cases {
                outs.push(format!("{}=>{}", write_literal(v)?, label(l)));
            }
            if let Some(d) = default {
                outs.push(format!("_=>{}", label(d)));
            }
            call_head(&[write_expr(value)?], "switch", &outs)
        }
        Kind::Jump { label: l } => call_head(&[], "jump", &[label(l)]),
        Kind::Parallel { labels } => call_head(&[], "parallel", &labels.iter().map(|l| label(l)).collect::<Vec<_>>()),
        Kind::Each { items, item, index, label: l, has_index } => {
            let mut outs = vec![item.clone().unwrap_or_else(|| "_".into())];
            if *has_index {
                outs.push(index.clone().unwrap_or_else(|| "_".into()));
            }
            outs.push(label(l));
            call_head(&[write_expr(items)?], "each", &outs)
        }
        Kind::Collect { items, item, index, label: l, value, target, has_index } => {
            let mut outs = vec![item.clone().unwrap_or_else(|| "_".into())];
            if *has_index {
                outs.push(index.clone().unwrap_or_else(|| "_".into()));
            }
            outs.push(label(l));
            outs.push(format!("{} -> {target}", write_expr(value)?));
            call_head(&[write_expr(items)?], "collect", &outs)
        }
        _ => return Err(KirError::Value("not a simple statement".into())),
    })
}

fn block(stmts: &[Stmt], depth: usize, out: &mut Vec<String>) -> Result<()> {
    for s in stmts {
        stmt(s, depth, out)?;
    }
    Ok(())
}

fn stmt(s: &Stmt, depth: usize, out: &mut Vec<String>) -> Result<()> {
    let pad = INDENT.repeat(depth);
    if !s.meta.is_empty() {
        out.push(format!("{pad}@meta {}", pairs(&s.meta)?));
    }
    if !s.hint.is_empty() {
        out.push(format!("{pad}@hint {}", pairs(&s.hint)?));
    }
    match &s.kind {
        Kind::Namespace { label, body } => {
            out.push(format!("{pad}{label}:"));
            block(body, depth + 1, out)?;
        }
        Kind::Dataflow { body } => {
            out.push(format!("{pad}@dataflow:"));
            block(body, depth + 1, out)?;
        }
        Kind::Try { body, handler, error_name } => {
            out.push(format!("{pad}@try:"));
            block(body, depth + 1, out)?;
            match error_name {
                Some(e) => out.push(format!("{pad}@except {e}:")),
                None => out.push(format!("{pad}@except:")),
            }
            block(handler, depth + 1, out)?;
        }
        Kind::Def(d) => {
            let mut params = Vec::with_capacity(d.params.len());
            for p in &d.params {
                let mut text = p.name.clone();
                if let Some(t) = &p.ty {
                    text += &format!(": {}", write_type(t));
                }
                if let Some(e) = &p.default {
                    text += &format!(" = {}", write_expr(e)?);
                }
                params.push(text);
            }
            let outs: Vec<String> = d
                .outputs
                .iter()
                .map(|o| match &o.ty {
                    Some(t) => format!("{}: {}", o.name, write_type(t)),
                    None => o.name.clone(),
                })
                .collect();
            out.push(format!("{pad}@def ({}){}({}):", params.join(", "), d.name, outs.join(", ")));
            block(&d.body, depth + 1, out)?;
        }
        Kind::TypeHints { entries } => {
            out.push(format!("{pad}@typehint:"));
            for e in entries {
                let ins: Vec<String> = e.inputs.iter().map(write_type).collect();
                let outs: Vec<String> = e.outputs.iter().map(write_type).collect();
                out.push(format!("{pad}{INDENT}({}){}({})", ins.join(", "), e.name, outs.join(", ")));
            }
        }
        _ => out.push(pad + &write_statement(s)?),
    }
    Ok(())
}

/// The canonical text of a program.
pub fn write(program: &Program) -> Result<String> {
    let mut out: Vec<String> = Vec::new();
    for u in &program.uses {
        let alias = match u.alias.as_deref() {
            Some(a) if !a.is_empty() => format!(" as {a}"),
            _ => String::new(),
        };
        out.push(format!("@use {}{alias}", write_literal(&Value::str(&u.library))?));
    }
    for i in &program.imports {
        out.push(format!("@import {} as {}", json_str(&i.module), i.alias));
    }
    for e in &program.exports {
        out.push(format!("@export {e}"));
    }
    if let Some(mode) = program.mode.as_deref().filter(|m| !m.is_empty()) {
        out.push(format!("@mode {mode}"));
    }
    if !out.is_empty() {
        out.push(String::new());
    }
    let mut previous_compound = false;
    for s in &program.body {
        let compound = matches!(s.kind, Kind::Def(_) | Kind::TypeHints { .. });
        if out.last().is_some_and(|l| !l.is_empty()) && (compound || previous_compound) {
            out.push(String::new());
        }
        stmt(s, 0, &mut out)?;
        previous_compound = compound;
    }
    while out.last().is_some_and(|l| l.is_empty()) {
        out.pop();
    }
    Ok(out.join("\n") + "\n")
}
