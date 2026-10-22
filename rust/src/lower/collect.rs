//! Correctness lowering: collect to a private fresh-list accumulator and each.
use crate::errors::{KirError, Result};
use crate::origins::derive_origin;
use crate::syntax::ast::{walk, Arg, Expr, Kind, Program, Stmt};
use crate::syntax::value::Value;
use crate::util::pyfmt::str_repr;
use std::collections::{HashMap, HashSet};

pub struct CollectExpander {
    counter: usize,
    used: HashSet<String>,
}

impl CollectExpander {
    pub fn new(program: &Program) -> Self {
        let mut used = HashSet::new();
        for stmt in walk(&program.body) {
            used.extend(stmt.reads().into_iter().chain(stmt.deferred_reads()).chain(stmt.writes()).map(str::to_string));
            if let Kind::Def(d) = &stmt.kind {
                used.extend(d.params.iter().map(|p| p.name.clone()));
                used.extend(d.outputs.iter().map(|p| p.name.clone()));
            } else if let Kind::Try { error_name: Some(name), .. } = &stmt.kind {
                used.insert(name.clone());
            }
        }
        Self { counter: 0, used }
    }
    fn fresh(&mut self) -> (String, String) {
        loop {
            self.counter += 1;
            let values = format!("collect__{}__values", self.counter);
            let items = format!("collect__{}__items", self.counter);
            if !self.used.contains(&values) && !self.used.contains(&items) {
                self.used.insert(values.clone());
                self.used.insert(items.clone());
                return (values, items);
            }
        }
    }
    pub fn block(&mut self, mut stmts: Vec<Stmt>) -> Result<Vec<Stmt>> {
        let namespaces: HashMap<String, usize> = stmts
            .iter()
            .enumerate()
            .filter_map(|(i, s)| match &s.kind {
                Kind::Namespace { label, .. } => Some((label.clone(), i)),
                _ => None,
            })
            .collect();
        let mut expansions = HashMap::new();
        // Prepare every body before descending, including bodies preceding owners.
        for i in 0..stmts.len() {
            let stmt = stmts[i].clone();
            let Kind::Collect { items, item, index, label, value, target, has_index } = &stmt.kind else { continue };
            let ns = *namespaces
                .get(label)
                .ok_or_else(|| KirError::Value(format!("collect namespace {} not found", str_repr(label))))?;
            let (accumulator, snapshot) = self.fresh();
            let mut append = Stmt::call(
                "kir.collect_append",
                vec![Arg::pos(Expr::Name(accumulator.clone())), Arg::pos(value.clone())],
                vec![Some(accumulator.clone())],
                stmt.line,
            );
            append.origin = derive_origin(stmt.origin.as_ref(), Some("collect.append"), &[]);
            let Kind::Namespace { body, .. } = &mut stmts[ns].kind else { unreachable!() };
            body.push(append);
            let mut snapshot_call =
                Stmt::call("kir.collect_items", vec![Arg::pos(items.clone())], vec![Some(snapshot.clone())], stmt.line);
            snapshot_call.origin = derive_origin(stmt.origin.as_ref(), Some("collect.items"), &[]);
            let mut init = Stmt::assign(accumulator.clone(), Expr::Literal(Value::List(vec![])), stmt.line);
            init.origin = derive_origin(stmt.origin.as_ref(), Some("collect.init"), &[]);
            let mut each = Stmt::new(
                Kind::Each {
                    items: Expr::Name(snapshot),
                    item: item.clone(),
                    index: index.clone(),
                    label: label.clone(),
                    has_index: *has_index,
                },
                stmt.line,
            );
            each.meta = stmt.meta.clone();
            each.hint = stmt.hint.clone();
            each.origin = stmt.origin.clone();
            let mut result = Stmt::assign(target.clone(), Expr::Name(accumulator), stmt.line);
            result.origin = derive_origin(stmt.origin.as_ref(), Some("collect.result"), &[]);
            expansions.insert(i, vec![snapshot_call, init, each, result]);
        }
        let mut out = Vec::new();
        for (i, stmt) in stmts.into_iter().enumerate() {
            if let Some(expansion) = expansions.remove(&i) {
                out.extend(expansion);
            } else {
                out.push(stmt);
            }
        }
        for stmt in &mut out {
            for body in stmt.children_mut() {
                *body = self.block(std::mem::take(body))?;
            }
        }
        Ok(out)
    }
}
