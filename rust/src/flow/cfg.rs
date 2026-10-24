//! Control-flow graph of one scope, and reaching definitions over it.
//!
//! Nodes are simple statements (assignments, calls, builtins) plus synthetic
//! `entry`, `exit` and `bind` nodes. A `bind` node sits at the start of an
//! `each` body (writing the item and index names) or of a named `@except`
//! handler (writing the error name). Edges are `Flow`, or `Exc` from a
//! statement inside a `@try` body to the handler, taken *before* the
//! statement's writes. `@def` bodies are separate scopes and are not entered.

use std::collections::{BTreeSet, HashMap};

use crate::syntax::ast::{Kind, Stmt, Uid};

/// Pseudo definition: "not written on this path".
pub const UNDEF: i64 = -1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NodeKind {
    Stmt,
    Entry,
    Exit,
    Bind,
    CollectSample,
    CollectDone,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EdgeKind {
    Flow,
    Exc,
}

#[derive(Debug)]
pub struct CNode<'a> {
    pub kind: NodeKind,
    pub stmt: Option<&'a Stmt>,
    pub writes: Vec<String>,
    pub reads: Vec<String>,
}

#[derive(Debug, Default)]
pub struct Cfg<'a> {
    pub nodes: Vec<CNode<'a>>,
    pub succ: Vec<Vec<(usize, EdgeKind)>>,
    pub entry: usize,
    pub exit: usize,
    /// Statement uid -> node.
    pub node_of: HashMap<Uid, usize>,
    /// Builtins naming a label that is not found.
    pub problems: Vec<(&'a Stmt, String)>,
    /// Namespace uid -> the builtins entering it.
    pub owners: HashMap<Uid, Vec<&'a Stmt>>,
    /// `each` / `@try` uid -> its bind node.
    pub binds: HashMap<Uid, usize>,
    pub samples: HashMap<Uid, usize>,
    pub completions: HashMap<Uid, usize>,
}

impl Cfg<'_> {
    pub fn preds(&self) -> Vec<Vec<(usize, EdgeKind)>> {
        let mut p = vec![Vec::new(); self.nodes.len()];
        for (a, outs) in self.succ.iter().enumerate() {
            for &(b, kind) in outs {
                p[b].push((a, kind));
            }
        }
        p
    }

    pub fn reachable(&self) -> BTreeSet<usize> {
        let mut seen = BTreeSet::from([self.entry]);
        let mut stack = vec![self.entry];
        while let Some(n) = stack.pop() {
            for &(b, _) in &self.succ[n] {
                if seen.insert(b) {
                    stack.push(b);
                }
            }
        }
        seen
    }
}

/// A control target resolved once the whole graph exists.
#[derive(Clone, Copy, Debug)]
enum Target {
    Node(usize),
    Ns(Uid),
}

type Table<'a> = HashMap<&'a str, &'a Stmt>;

struct Builder<'a> {
    g: Cfg<'a>,
    pending: Vec<(usize, Target, EdgeKind)>,
    ns_entry: HashMap<Uid, Target>,
}

impl<'a> Builder<'a> {
    fn new_node(&mut self, kind: NodeKind, stmt: Option<&'a Stmt>, writes: Vec<String>, reads: Vec<String>) -> usize {
        self.g.nodes.push(CNode { kind, stmt, writes, reads });
        self.g.succ.push(Vec::new());
        let n = self.g.nodes.len() - 1;
        if kind == NodeKind::Stmt {
            if let Some(s) = stmt {
                self.g.node_of.insert(s.uid, n);
            }
        }
        n
    }

    fn edge_later(&mut self, a: usize, target: Target, kind: EdgeKind) {
        self.pending.push((a, target, kind));
    }

    /// Build a block; return a target for its first statement.
    fn block(&mut self, stmts: &'a [Stmt], scopes: &[&Table<'a>], cont: Target) -> Target {
        let mut local: Table<'a> = HashMap::new();
        for s in stmts {
            if let Kind::Namespace { label, .. } = &s.kind {
                local.insert(label, s);
            }
        }
        let mut chain: Vec<&Table<'a>> = Vec::with_capacity(scopes.len() + 1);
        chain.push(&local);
        chain.extend_from_slice(scopes);
        let mut after = vec![cont; stmts.len() + 1];
        let mut nodes: Vec<(usize, usize)> = Vec::new();
        for i in (0..stmts.len()).rev() {
            let s = &stmts[i];
            let nxt = after[i + 1];
            match &s.kind {
                Kind::Namespace { .. } | Kind::Def(_) | Kind::TypeHints { .. } => after[i] = nxt,
                Kind::Dataflow { body } => after[i] = self.block(body, &chain, nxt),
                Kind::Try { body, handler, error_name } => {
                    let start = self.g.nodes.len();
                    let body_entry = self.block(body, &chain, nxt);
                    let end = self.g.nodes.len();
                    let mut handler_entry = self.block(handler, &chain, nxt);
                    if let Some(e) = error_name {
                        let bind = self.new_node(NodeKind::Bind, None, vec![e.clone()], vec![]);
                        self.g.binds.insert(s.uid, bind);
                        self.edge_later(bind, handler_entry, EdgeKind::Flow);
                        handler_entry = Target::Node(bind);
                    }
                    for n in start..end {
                        if self.g.nodes[n].kind == NodeKind::Stmt {
                            self.edge_later(n, handler_entry, EdgeKind::Exc);
                        }
                    }
                    after[i] = body_entry;
                }
                _ => {
                    let writes = if matches!(s.kind, Kind::Each { .. } | Kind::Collect { .. }) {
                        vec![]
                    } else {
                        owned(s.writes())
                    };
                    let n = self.new_node(NodeKind::Stmt, Some(s), writes, owned(s.reads()));
                    if let Kind::Collect { target, .. } = &s.kind {
                        let sample = self.new_node(NodeKind::CollectSample, Some(s), vec![], owned(s.deferred_reads()));
                        let done = self.new_node(NodeKind::CollectDone, Some(s), vec![target.clone()], vec![]);
                        self.g.samples.insert(s.uid, sample);
                        self.g.completions.insert(s.uid, done);
                        self.g.succ[sample].push((n, EdgeKind::Flow));
                        self.edge_later(done, nxt, EdgeKind::Flow);
                    }
                    nodes.push((i, n));
                    after[i] = Target::Node(n);
                }
            }
        }
        // Namespace bodies: the continuation depends on the builtin that owns them.
        let mut cont_of: HashMap<Uid, Target> = HashMap::new();
        let mut by_index: Vec<(usize, usize)> = nodes.clone();
        by_index.sort();
        for &(i, n) in &by_index {
            match &stmts[i].kind {
                Kind::Parallel { labels } => {
                    let arms: Vec<Option<&&Stmt>> = labels.iter().map(|l| local.get(l.as_str())).collect();
                    for (k, ns) in arms.iter().enumerate() {
                        let Some(ns) = ns else { continue };
                        let next_arm = arms.get(k + 1).copied().flatten();
                        let target = match next_arm {
                            Some(next) => Target::Ns(next.uid),
                            None => after[i + 1],
                        };
                        cont_of.insert(ns.uid, target);
                    }
                }
                Kind::Each { label, .. } | Kind::Collect { label, .. } => {
                    if let Some(ns) = local.get(label.as_str()) {
                        let end = self.g.samples.get(&stmts[i].uid).copied().unwrap_or(n);
                        cont_of.insert(ns.uid, Target::Node(end));
                    }
                }
                _ => {}
            }
        }
        for (i, s) in stmts.iter().enumerate() {
            if let Kind::Namespace { body, .. } = &s.kind {
                let cont_ns = cont_of.get(&s.uid).copied().unwrap_or(after[i + 1]);
                let entry = self.block(body, &chain, cont_ns);
                self.ns_entry.insert(s.uid, entry);
            }
        }
        for &(i, n) in &nodes {
            self.wire(&stmts[i], n, &chain, &local, after[i + 1]);
        }
        after[0]
    }

    fn enter(&mut self, s: &'a Stmt, label: &str, scopes: &[&Table<'a>]) -> Option<Target> {
        for table in scopes {
            if let Some(ns) = table.get(label) {
                self.g.owners.entry(ns.uid).or_default().push(s);
                return Some(Target::Ns(ns.uid));
            }
        }
        self.g.problems.push((s, label.to_string()));
        None
    }

    fn wire(&mut self, s: &'a Stmt, n: usize, chain: &[&Table<'a>], local: &Table<'a>, nxt: Target) {
        match &s.kind {
            Kind::Branch { .. } | Kind::Switch { .. } => {
                for label in s.labels_entered() {
                    if let Some(t) = self.enter(s, label, &[local]) {
                        self.edge_later(n, t, EdgeKind::Flow);
                    }
                }
            }
            Kind::Parallel { labels } => {
                let targets: Vec<Option<Target>> = labels.iter().map(|l| self.enter(s, l, &[local])).collect();
                if let Some(Some(t)) = targets.first() {
                    self.edge_later(n, *t, EdgeKind::Flow);
                }
            }
            Kind::Jump { label } => {
                if let Some(t) = self.enter(s, label, chain) {
                    self.edge_later(n, t, EdgeKind::Flow);
                }
            }
            Kind::Each { label, item, index, .. } | Kind::Collect { label, item, index, .. } => {
                if let Some(t) = self.enter(s, label, &[local]) {
                    let names: Vec<String> = item.iter().chain(index.iter()).cloned().collect();
                    let bind = self.new_node(NodeKind::Bind, None, names, vec![]);
                    self.g.binds.insert(s.uid, bind);
                    self.g.succ[n].push((bind, EdgeKind::Flow));
                    self.edge_later(bind, t, EdgeKind::Flow);
                }
                if let Some(done) = self.g.completions.get(&s.uid) {
                    self.g.succ[n].push((*done, EdgeKind::Flow));
                } else {
                    self.edge_later(n, nxt, EdgeKind::Flow);
                }
            }
            _ => self.edge_later(n, nxt, EdgeKind::Flow),
        }
    }

    fn resolve(&self, mut t: Target) -> usize {
        loop {
            match t {
                Target::Node(n) => return n,
                Target::Ns(uid) => t = self.ns_entry[&uid],
            }
        }
    }
}

fn owned(names: Vec<&str>) -> Vec<String> {
    names.into_iter().map(str::to_string).collect()
}

/// The CFG of one scope; `params` are written at the entry.
pub fn build_cfg<'a>(body: &'a [Stmt], params: &[String]) -> Cfg<'a> {
    let mut b = Builder { g: Cfg::default(), pending: Vec::new(), ns_entry: HashMap::new() };
    let entry = b.new_node(NodeKind::Entry, None, params.to_vec(), vec![]);
    let exit = b.new_node(NodeKind::Exit, None, vec![], vec![]);
    let first = b.block(body, &[], Target::Node(exit));
    b.edge_later(entry, first, EdgeKind::Flow);
    let pending = std::mem::take(&mut b.pending);
    for (a, t, kind) in pending {
        let target = b.resolve(t);
        b.g.succ[a].push((target, kind));
    }
    b.g.entry = entry;
    b.g.exit = exit;
    b.g
}

/// Reaching definitions: the IN set of every node as `(name, defining node)`
/// pairs, with `UNDEF` marking a path with no write.
pub struct Reaching {
    ids: HashMap<String, u32>,
    inn: Vec<BTreeSet<(u32, i64)>>,
}

impl Reaching {
    /// The definitions of `name` reaching node `n`.
    pub fn defs_of(&self, n: usize, name: &str) -> BTreeSet<i64> {
        match self.ids.get(name) {
            None => BTreeSet::new(),
            Some(&id) => self.inn[n].range((id, i64::MIN)..=(id, i64::MAX)).map(|&(_, d)| d).collect(),
        }
    }
}

/// Edges `(a, b)` closing a loop: into a node still open on a depth-first walk
/// from the entry, successors taken in order.
pub fn back_edges(g: &Cfg) -> BTreeSet<(usize, usize)> {
    let mut out = BTreeSet::new();
    // 1 open, 2 done
    let mut state: HashMap<usize, u8> = HashMap::from([(g.entry, 1)]);
    let mut stack: Vec<(usize, usize)> = vec![(g.entry, 0)];
    while let Some(top) = stack.last_mut() {
        let n = top.0;
        let Some(&(b, _)) = g.succ[n].get(top.1) else {
            state.insert(n, 2);
            stack.pop();
            continue;
        };
        top.1 += 1;
        match state.get(&b) {
            Some(1) => {
                out.insert((n, b));
            }
            None => {
                state.insert(b, 1);
                stack.push((b, 0));
            }
            _ => {}
        }
    }
    out
}

/// Reaching definitions over `g`; `undefined` names start as `UNDEF` at the entry.
pub fn reaching(g: &Cfg, undefined: &[String]) -> Reaching {
    reaching_with(g, undefined, false)
}

/// `reaching`; `forward` leaves out the edges closing loops (`back_edges`):
/// what reaches a node on the way in.
pub fn reaching_with(g: &Cfg, undefined: &[String], forward: bool) -> Reaching {
    let mut ids: HashMap<String, u32> = HashMap::new();
    let intern = |name: &str, ids: &mut HashMap<String, u32>| -> u32 {
        let next = ids.len() as u32;
        *ids.entry(name.to_string()).or_insert(next)
    };
    let writes: Vec<Vec<u32>> =
        g.nodes.iter().map(|n| n.writes.iter().map(|w| intern(w, &mut ids)).collect()).collect();
    for n in &g.nodes {
        for r in &n.reads {
            intern(r, &mut ids);
        }
    }
    let start: BTreeSet<(u32, i64)> = undefined.iter().map(|x| (intern(x, &mut ids), UNDEF)).collect();
    let mut preds = g.preds();
    if forward {
        let back = back_edges(g);
        for (n, ps) in preds.iter_mut().enumerate() {
            ps.retain(|&(p, _)| !back.contains(&(p, n)));
        }
    }
    let mut out: Vec<BTreeSet<(u32, i64)>> = vec![BTreeSet::new(); g.nodes.len()];
    let mut inn: Vec<BTreeSet<(u32, i64)>> = vec![BTreeSet::new(); g.nodes.len()];
    let order: Vec<usize> = g.reachable().into_iter().collect();
    let mut changed = true;
    while changed {
        changed = false;
        for &n in &order {
            let mut acc = if n == g.entry { start.clone() } else { BTreeSet::new() };
            for &(p, kind) in &preds[n] {
                let src = if kind == EdgeKind::Exc { &inn[p] } else { &out[p] };
                acc.extend(src.iter().copied());
            }
            let w = &writes[n];
            let mut new_out: BTreeSet<(u32, i64)> = acc.iter().filter(|(x, _)| !w.contains(x)).copied().collect();
            new_out.extend(w.iter().map(|&x| (x, n as i64)));
            if acc != inn[n] || new_out != out[n] {
                inn[n] = acc;
                out[n] = new_out;
                changed = true;
            }
        }
    }
    Reaching { ids, inn }
}
