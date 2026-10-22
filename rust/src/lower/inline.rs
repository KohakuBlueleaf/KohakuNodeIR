//! The `inline` pass: every `@def` call becomes a renamed copy of its body (passes.md).

use std::collections::HashMap;

use indexmap::IndexMap;

use crate::origins::derive_origin;
use crate::syntax::ast::{walk, walk_mut, Arg, Def, Expr, Kind, Origin, Program, Stmt};
use crate::syntax::value::Value;

fn rename_expr(e: &mut Expr, f: &dyn Fn(&str) -> String) {
    if let Expr::Name(n) = e {
        *n = f(n);
    }
}

fn rename_opt(o: &mut Option<String>, f: &dyn Fn(&str) -> String) {
    if let Some(x) = o {
        *x = f(x);
    }
}

/// Rename every name and label in place with `f`.
pub fn rename(stmts: &mut [Stmt], f: &dyn Fn(&str) -> String) {
    for s in stmts {
        match &mut s.kind {
            Kind::Assign { target, value, .. } => {
                *target = f(target);
                rename_expr(value, f);
            }
            Kind::Call { args, outs, .. } => {
                for a in args {
                    rename_expr(&mut a.value, f);
                }
                for o in outs {
                    rename_opt(o, f);
                }
            }
            Kind::Branch { cond, true_label, false_label } => {
                rename_expr(cond, f);
                *true_label = f(true_label);
                *false_label = f(false_label);
            }
            Kind::Switch { value, cases, default } => {
                rename_expr(value, f);
                for (_, label) in cases {
                    *label = f(label);
                }
                rename_opt(default, f);
            }
            Kind::Jump { label } => *label = f(label),
            Kind::Parallel { labels } => {
                for l in labels {
                    *l = f(l);
                }
            }
            Kind::Each { items, item, index, label, .. } => {
                rename_expr(items, f);
                rename_opt(item, f);
                rename_opt(index, f);
                *label = f(label);
            }
            Kind::Namespace { label, .. } => *label = f(label),
            Kind::Try { error_name, .. } => rename_opt(error_name, f),
            _ => {}
        }
        for body in s.children_mut() {
            rename(body, f);
        }
    }
}

/// Inlines the `@def`s of a program (its own, already sorted, copies).
pub struct Inliner {
    defs: IndexMap<String, Def>,
    origins: HashMap<String, Origin>,
    counter: HashMap<String, usize>,
}

impl Inliner {
    pub fn new(program: &Program) -> Inliner {
        let mut defs = IndexMap::new();
        let mut origins = HashMap::new();
        for s in walk(&program.body) {
            if let Kind::Def(d) = &s.kind {
                defs.insert(d.name.clone(), d.clone());
                if let Some(origin) = &s.origin {
                    origins.insert(d.name.clone(), origin.clone());
                }
            }
        }
        Inliner { defs, origins, counter: HashMap::new() }
    }

    pub fn block(&mut self, stmts: Vec<Stmt>) -> Vec<Stmt> {
        let mut out = Vec::with_capacity(stmts.len());
        for mut s in stmts {
            match &s.kind {
                Kind::Def(_) => continue,
                Kind::Call { name, .. } => {
                    if let Some(d) = self.defs.get(name).cloned() {
                        out.extend(self.expand(s, &d));
                        continue;
                    }
                }
                _ => {}
            }
            for body in s.children_mut() {
                *body = self.block(std::mem::take(body));
            }
            out.push(s);
        }
        out
    }

    fn expand(&mut self, call: Stmt, d: &Def) -> Vec<Stmt> {
        let k = self.counter.entry(d.name.clone()).or_insert(0);
        *k += 1;
        let prefix = format!("{}__{}__", d.name, k);
        let f = |x: &str| format!("{prefix}{x}");
        let Kind::Call { args, outs: targets, .. } = &call.kind else { unreachable!("a call") };
        let positional: Vec<&Arg> = args.iter().filter(|a| a.key.is_none()).collect();
        let mut given: HashMap<&str, &Expr> = HashMap::new();
        for (p, a) in d.params.iter().zip(&positional) {
            given.insert(&p.name, &a.value);
        }
        for a in args {
            if let Some(key) = &a.key {
                given.insert(key, &a.value);
            }
        }
        let source = call.origin.as_ref().or_else(|| self.origins.get(&d.name)).cloned();
        let mut out = Vec::new();
        for p in &d.params {
            let value = match given.get(p.name.as_str()) {
                Some(e) => (*e).clone(),
                None => p.default.clone().unwrap_or(Expr::Literal(Value::None)),
            };
            let mut stmt = Stmt::assign(f(&p.name), value, call.line);
            stmt.origin = derive_origin(source.as_ref(), Some("inline.arg"), &[]);
            out.push(stmt);
        }
        let mut body = d.body.clone();
        for s in &mut body {
            s.renew_uids();
        }
        if let Some(origin) = &call.origin {
            let mut ancestry = origin.calls.clone();
            ancestry.push(origin.clone());
            walk_mut(&mut body, &mut |stmt| {
                stmt.origin = derive_origin(stmt.origin.as_ref(), None, &ancestry);
            });
        }
        rename(&mut body, &f);
        out.extend(self.block(body));
        for (o, target) in d.outputs.iter().zip(targets) {
            if let Some(t) = target {
                let mut stmt = Stmt::assign(t.clone(), Expr::Name(f(&o.name)), call.line);
                stmt.origin = derive_origin(source.as_ref(), Some("inline.output"), &[]);
                out.push(stmt);
            }
        }
        if let Some(first) = out.first_mut() {
            let mut hint = call.hint.clone();
            hint.extend(std::mem::take(&mut first.hint));
            first.hint = hint;
        }
        out
    }
}
