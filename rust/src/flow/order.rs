//! Stable topological ordering of `@dataflow:` blocks (passes.md, `order_dataflow`).

use std::cmp::Reverse;
use std::collections::{BTreeSet, BinaryHeap, HashMap};

use crate::syntax::ast::{Kind, Program, Stmt};

/// A dependency cycle; holds the line of the first statement left in it.
#[derive(Debug)]
pub struct DataflowCycle {
    pub line: Option<usize>,
}

/// Statements after every statement whose output they read; earliest first when tied.
pub fn order_block(stmts: Vec<Stmt>, is_ordered: &dyn Fn(&Stmt) -> bool) -> Result<Vec<Stmt>, DataflowCycle> {
    let mut deps: Vec<BTreeSet<usize>> = vec![BTreeSet::new(); stmts.len()];
    let mut writers: HashMap<&str, Vec<usize>> = HashMap::new();
    for (i, s) in stmts.iter().enumerate() {
        for name in s.writes() {
            writers.entry(name).or_default().push(i);
        }
    }
    let mut last_ordered = None;
    for (i, s) in stmts.iter().enumerate() {
        for name in s.reads() {
            if let Some(ws) = writers.get(name) {
                deps[i].extend(ws.iter().copied().filter(|&j| j != i));
            }
        }
        if is_ordered(s) {
            if let Some(j) = last_ordered {
                deps[i].insert(j);
            }
            last_ordered = Some(i);
        }
    }
    let mut remaining: Vec<usize> = deps.iter().map(BTreeSet::len).collect();
    let mut users: Vec<Vec<usize>> = vec![Vec::new(); stmts.len()];
    for (i, d) in deps.iter().enumerate() {
        for &j in d {
            users[j].push(i);
        }
    }
    let mut ready: BinaryHeap<Reverse<usize>> =
        remaining.iter().enumerate().filter(|(_, &r)| r == 0).map(|(i, _)| Reverse(i)).collect();
    let mut order = Vec::with_capacity(stmts.len());
    while let Some(Reverse(i)) = ready.pop() {
        order.push(i);
        for &u in &users[i] {
            remaining[u] -= 1;
            if remaining[u] == 0 {
                ready.push(Reverse(u));
            }
        }
    }
    if order.len() != stmts.len() {
        let first = remaining.iter().position(|&r| r > 0).expect("a statement is left");
        return Err(DataflowCycle { line: stmts[first].line });
    }
    let mut slots: Vec<Option<Stmt>> = stmts.into_iter().map(Some).collect();
    Ok(order.into_iter().map(|i| slots[i].take().expect("each index once")).collect())
}

fn sort(stmts: Vec<Stmt>, is_ordered: &dyn Fn(&Stmt) -> bool) -> Result<Vec<Stmt>, DataflowCycle> {
    let mut out = Vec::with_capacity(stmts.len());
    for mut s in stmts {
        if let Kind::Dataflow { body } = &mut s.kind {
            *body = order_block(std::mem::take(body), is_ordered)?;
        }
        for body in s.children_mut() {
            *body = sort(std::mem::take(body), is_ordered)?;
        }
        out.push(s);
    }
    Ok(out)
}

/// Sort every `@dataflow:` block in place; a `@mode dataflow` file is one block.
pub fn sort_dataflow(program: &mut Program, is_ordered: &dyn Fn(&Stmt) -> bool) -> Result<(), DataflowCycle> {
    let mut body = std::mem::take(&mut program.body);
    if program.mode.as_deref() == Some("dataflow") {
        body = order_block(body, is_ordered)?;
    }
    program.body = sort(body, is_ordered)?;
    Ok(())
}
