//! The `expand_each` pass: `each` as a loop of v1 constructs (passes.md).

use std::collections::{HashMap, HashSet};

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
        self.k += 1;
        let p = format!("each__{}__", self.k);
        let (lp, done) = (format!("each__{}", self.k), format!("each__{}__done", self.k));
        let (items, index, item, more) = (p.clone() + "items", p.clone() + "index", p.clone() + "item", p + "more");
        let name = |n: &str| Expr::Name(n.to_string());
        let mut body = Vec::new();
        if let Some(x) = &s_item {
            body.push(Stmt::assign(x.clone(), name(&item), line));
        }
        if let Some(x) = &s_index {
            body.push(Stmt::assign(x.clone(), name(&index), line));
        }
        let ns_line = ns.as_ref().map_or(line, |n| n.line);
        if let Some(Stmt { kind: Kind::Namespace { body: ns_body, .. }, .. }) = ns {
            body.extend(self.block(ns_body));
        }
        body.push(Stmt::call("kir.next_index", vec![Arg::pos(name(&index))], vec![Some(index.clone())], line));
        body.push(Stmt::new(Kind::Jump { label: lp.clone() }, line));
        let header = vec![
            Stmt::call(
                "kir.item_at",
                vec![Arg::pos(name(&items)), Arg::pos(name(&index))],
                vec![Some(item.clone()), Some(more.clone())],
                line,
            ),
            Stmt::new(Kind::Branch { cond: name(&more), true_label: label.clone(), false_label: done.clone() }, line),
            Stmt::new(Kind::Namespace { label, body }, ns_line),
            Stmt::new(Kind::Namespace { label: done, body: vec![] }, line),
        ];
        let mut to_list = Stmt::call("kir.to_list", vec![Arg::pos(source)], vec![Some(items)], line);
        to_list.hint = s.hint;
        vec![
            to_list,
            Stmt::assign(index, Expr::Literal(Value::int(0)), line),
            Stmt::new(Kind::Jump { label: lp.clone() }, line),
            Stmt::new(Kind::Namespace { label: lp, body: header }, line),
        ]
    }
}
