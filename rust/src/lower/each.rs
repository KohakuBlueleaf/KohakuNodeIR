//! The `expand_each` pass: `each` as a loop of v1 constructs (passes.md).

use std::collections::{HashMap, HashSet};

use crate::origins::derive_origin;
use crate::syntax::ast::{Arg, Expr, Kind, Stmt};
use crate::syntax::value::Value;

#[derive(Default)]
pub struct EachExpander {
    k: usize,
}

impl EachExpander {
    pub fn block(&mut self, stmts: Vec<Stmt>) -> Vec<Stmt> {
        let owned: HashSet<String> = stmts
            .iter()
            .filter_map(|s| match &s.kind {
                Kind::Each { label, .. } => Some(label.clone()),
                _ => None,
            })
            .collect();
        let mut bodies: HashMap<String, Stmt> = HashMap::new();
        let mut rest = Vec::with_capacity(stmts.len());
        for s in stmts {
            match &s.kind {
                Kind::Namespace { label, .. } if owned.contains(label) => {
                    bodies.insert(label.clone(), s);
                }
                _ => rest.push(s),
            }
        }
        let mut out = Vec::with_capacity(rest.len());
        for mut s in rest {
            if let Kind::Each { label, .. } = &s.kind {
                let ns = bodies.get(label).cloned();
                out.extend(self.expand(s, ns));
                continue;
            }
            for body in s.children_mut() {
                *body = self.block(std::mem::take(body));
            }
            out.push(s);
        }
        out
    }

    fn expand(&mut self, s: Stmt, ns: Option<Stmt>) -> Vec<Stmt> {
        let Kind::Each { items: source, item: s_item, index: s_index, label, .. } = s.kind else {
            unreachable!("an each")
        };
        let line = s.line;
        let generated = |mut stmt: Stmt, role: &str| {
            stmt.origin = derive_origin(s.origin.as_ref(), Some(&format!("each.{role}")), &[]);
            stmt
        };
        self.k += 1;
        let p = format!("each__{}__", self.k);
        let (lp, done) = (format!("each__{}", self.k), format!("each__{}__done", self.k));
        let (items, index, item, more) = (p.clone() + "items", p.clone() + "index", p.clone() + "item", p + "more");
        let name = |n: &str| Expr::Name(n.to_string());
        let mut body = Vec::new();
        if let Some(x) = &s_item {
            body.push(generated(Stmt::assign(x.clone(), name(&item), line), "item"));
        }
        if let Some(x) = &s_index {
            body.push(generated(Stmt::assign(x.clone(), name(&index), line), "index"));
        }
        let ns_line = ns.as_ref().map_or(line, |n| n.line);
        let ns_origin = match &ns {
            Some(n) => n.origin.clone(),
            None => derive_origin(s.origin.as_ref(), Some("each.body"), &[]),
        };
        if let Some(Stmt { kind: Kind::Namespace { body: ns_body, .. }, .. }) = ns {
            body.extend(self.block(ns_body));
        }
        body.push(generated(
            Stmt::call("kir.next_index", vec![Arg::pos(name(&index))], vec![Some(index.clone())], line),
            "next",
        ));
        body.push(generated(Stmt::new(Kind::Jump { label: lp.clone() }, line), "repeat"));
        let mut namespace = Stmt::new(Kind::Namespace { label: label.clone(), body }, ns_line);
        namespace.origin = ns_origin;
        let header = vec![
            generated(
                Stmt::call(
                    "kir.item_at",
                    vec![Arg::pos(name(&items)), Arg::pos(name(&index))],
                    vec![Some(item.clone()), Some(more.clone())],
                    line,
                ),
                "test",
            ),
            generated(
                Stmt::new(Kind::Branch { cond: name(&more), true_label: label, false_label: done.clone() }, line),
                "branch",
            ),
            namespace,
            generated(Stmt::new(Kind::Namespace { label: done, body: vec![] }, line), "done"),
        ];
        let mut to_list = Stmt::call("kir.to_list", vec![Arg::pos(source)], vec![Some(items)], line);
        to_list.hint = s.hint;
        vec![
            generated(to_list, "items"),
            generated(Stmt::assign(index, Expr::Literal(Value::int(0)), line), "init"),
            generated(Stmt::new(Kind::Jump { label: lp.clone() }, line), "enter"),
            generated(Stmt::new(Kind::Namespace { label: lp, body: header }, line), "loop"),
        ]
    }
}
