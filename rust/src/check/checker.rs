//! The checker: every rule of checks.md.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fmt;

use indexmap::IndexMap;

use crate::flow::cfg::{build_cfg, reaching, UNDEF};
use crate::flow::order::sort_dataflow;
use crate::sig::env::{NodeEnv, Resolution};
use crate::sig::types::{fits, literal_type, type_text};
use crate::syntax::ast::{walk, Def, Expr, Kind, Origin, Program, Stmt, TypeExpr};
use crate::util::pyfmt::{str_list_repr, str_repr};

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Diagnostic {
    pub code: String,
    pub message: String,
    pub line: Option<usize>,
}

impl Diagnostic {
    pub fn new(code: &str, message: impl Into<String>, line: Option<usize>) -> Diagnostic {
        Diagnostic { code: code.to_string(), message: message.into(), line }
    }

    pub fn is_error(&self) -> bool {
        self.code.starts_with('E')
    }

    pub fn severity(&self) -> &'static str {
        if self.is_error() {
            "error"
        } else {
            "warning"
        }
    }
}

impl fmt::Display for Diagnostic {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if let Some(line) = self.line {
            write!(f, "line {line}: ")?;
        }
        write!(f, "{} {}", self.code, self.message)
    }
}

fn is_control(s: &Stmt) -> bool {
    matches!(
        s.kind,
        Kind::Branch { .. }
            | Kind::Switch { .. }
            | Kind::Jump { .. }
            | Kind::Parallel { .. }
            | Kind::Each { .. }
            | Kind::Namespace { .. }
            | Kind::Try { .. }
    )
}

/// Statements of one scope: like `walk`, but not into `@def` bodies.
fn scope_walk(stmts: &[Stmt]) -> Vec<&Stmt> {
    fn go<'a>(stmts: &'a [Stmt], out: &mut Vec<&'a Stmt>) {
        for s in stmts {
            if matches!(s.kind, Kind::Def(_)) {
                continue;
            }
            out.push(s);
            match &s.kind {
                Kind::Namespace { body, .. } | Kind::Dataflow { body } => go(body, out),
                Kind::Try { body, handler, .. } => {
                    go(body, out);
                    go(handler, out);
                }
                _ => {}
            }
        }
    }
    let mut out = Vec::new();
    go(stmts, &mut out);
    out
}

struct Checker<'e> {
    env: &'e NodeEnv,
    out: Vec<Diagnostic>,
}

impl Checker<'_> {
    fn add(&mut self, code: &str, message: String, line: Option<usize>) {
        self.out.push(Diagnostic::new(code, message, line));
    }

    fn add_origin(&mut self, code: &str, mut message: String, line: Option<usize>, origin: Option<&Origin>) {
        if let Some(origin) = origin.filter(|o| o.module != "<text>") {
            let definition = origin.definition.as_ref().map_or(String::new(), |d| format!("::{d}"));
            message = format!("{}{definition}: {message}", origin.module);
        }
        self.add(code, message, line);
    }

    fn add_at(&mut self, code: &str, message: String, stmt: Option<&Stmt>) {
        self.add_origin(code, message, stmt.and_then(|s| s.line), stmt.and_then(|s| s.origin.as_ref()));
    }

    // ------------------------------------------------------------ whole program
    fn program(&mut self, p: &mut Program) {
        self.reserved(p);
        if p.mode.as_deref() == Some("dataflow") {
            if let Some(s) = walk(&p.body).into_iter().find(|s| is_control(s)) {
                self.add_at("E060", "@mode dataflow file contains control flow".into(), Some(s));
            }
        }
        let mut e061 = Vec::new();
        for s in walk(&p.body) {
            if let Kind::Dataflow { body } = &s.kind {
                e061.extend(body.iter().filter(|inner| !inner.is_simple()));
            }
        }
        for stmt in e061 {
            self.add_at("E061", "@dataflow blocks hold only assignments and calls".into(), Some(stmt));
        }
        let env = self.env;
        let is_ordered = |s: &Stmt| match &s.kind {
            Kind::Call { name, .. } => env.is_ordered(name),
            _ => false,
        };
        if let Err(cycle) = sort_dataflow(p, &is_ordered) {
            self.add_origin("E033", "dependency cycle in @dataflow block".into(), cycle.line, cycle.origin.as_deref());
            return;
        }
        self.recursion(p);
        self.scope(&p.body, &[], None);
        for s in walk(&p.body) {
            if let Kind::Def(d) = &s.kind {
                let params: Vec<String> = d.params.iter().map(|x| x.name.clone()).collect();
                self.scope(&d.body, &params, Some((d, s)));
            }
        }
    }

    fn reserved(&mut self, p: &Program) {
        for s in walk(&p.body) {
            let mut names: Vec<&str> = s.writes();
            names.extend(s.reads());
            names.extend(s.labels_entered());
            match &s.kind {
                Kind::Namespace { label, .. } => names.push(label),
                Kind::Def(d) => {
                    names.extend(d.params.iter().map(|x| x.name.as_str()));
                    names.extend(d.outputs.iter().map(|x| x.name.as_str()));
                }
                Kind::Try { error_name: Some(e), .. } => names.push(e),
                _ => {}
            }
            for n in names {
                if n.contains("__") {
                    self.add_at(
                        "E013",
                        format!("name or label {} contains '__', which is reserved", str_repr(n)),
                        Some(s),
                    );
                }
            }
            if let Kind::Call { name, .. } = &s.kind {
                if name.starts_with("kir.") && !self.env.internal {
                    self.add_at("E013", format!("node {} uses the reserved 'kir.' prefix", str_repr(name)), Some(s));
                }
            }
        }
    }

    fn recursion(&mut self, p: &Program) {
        let mut defs: IndexMap<&str, &Stmt> = IndexMap::new();
        for s in walk(&p.body) {
            if let Kind::Def(d) = &s.kind {
                defs.insert(&d.name, s);
            }
        }
        let mut calls: HashMap<&str, BTreeSet<String>> = HashMap::new();
        for (&name, &s) in &defs {
            let Kind::Def(d) = &s.kind else { unreachable!("defs holds @def statements") };
            let called = walk(&d.body)
                .into_iter()
                .filter_map(|c| match &c.kind {
                    Kind::Call { name, .. } if defs.contains_key(name.as_str()) => Some(name.clone()),
                    _ => None,
                })
                .collect();
            calls.insert(name, called);
        }
        for (&start, &s) in &defs {
            let mut stack: Vec<&str> = calls[start].iter().map(String::as_str).collect();
            let mut seen = HashSet::new();
            while let Some(n) = stack.pop() {
                if n == start {
                    self.add_at("E050", format!("@def {} calls itself", str_repr(start)), Some(s));
                    break;
                }
                if seen.insert(n) {
                    stack.extend(calls[n].iter().map(String::as_str));
                }
            }
        }
    }

    // ------------------------------------------------------------ one scope
    fn scope(&mut self, body: &[Stmt], params: &[String], d: Option<(&Def, &Stmt)>) {
        let local = scope_walk(body);
        let types = self.name_types(&local, d.map(|(d, _)| d));
        for s in &local {
            match &s.kind {
                Kind::Call { .. } => self.call(s, &types),
                Kind::Branch { cond, .. } => {
                    if let Some(t) = expr_type(cond, &types) {
                        if !t.is_any() && !fits(Some(&t), Some(&TypeExpr::name("bool"))) {
                            self.add_at(
                                "E041",
                                format!("branch condition has type {}, not bool", type_text(Some(&t))),
                                Some(s),
                            );
                        }
                    }
                }
                _ => {}
            }
        }
        let g = build_cfg(body, params);
        for (s, label) in &g.problems {
            self.add_at("E030", format!("label `{label}` not found"), Some(s));
        }
        let namespaces: Vec<&Stmt> =
            local.iter().copied().filter(|s| matches!(s.kind, Kind::Namespace { .. })).collect();
        for ns in &namespaces {
            let Kind::Namespace { label, body: ns_body } = &ns.kind else { unreachable!("namespace") };
            let owners = g.owners.get(&ns.uid).map(Vec::as_slice).unwrap_or(&[]);
            let non_jump = owners.iter().filter(|o| !matches!(o.kind, Kind::Jump { .. })).count();
            if non_jump > 1 {
                self.add_at("E031", format!("namespace `{label}` is entered by more than one builtin"), Some(ns));
            }
            if owners.is_empty() {
                self.add_at("W001", format!("namespace `{label}` is never entered"), Some(ns));
            }
            if owners.iter().any(|o| matches!(o.kind, Kind::Each { .. })) {
                let inside: HashSet<usize> = walk(ns_body).iter().map(|x| x.uid).collect();
                for o in owners {
                    if matches!(o.kind, Kind::Jump { .. }) && !inside.contains(&o.uid) {
                        self.add_at("E032", format!("jump into the body of each `{label}`"), Some(o));
                    }
                }
            }
        }
        let mut names: BTreeSet<String> = BTreeSet::new();
        for s in &local {
            names.extend(s.writes().into_iter().chain(s.reads()).map(str::to_string));
        }
        for p in params {
            names.remove(p);
        }
        let names: Vec<String> = names.into_iter().collect();
        let inn = reaching(&g, &names);
        let reach = g.reachable();
        let mut read_names: HashSet<String> = HashSet::new();
        for &n in &reach {
            let node = &g.nodes[n];
            for name in &node.reads {
                read_names.insert(name.clone());
                if inn.defs_of(n, name).contains(&UNDEF) {
                    self.add_at("E020", format!("{} may be read before it is written", str_repr(name)), node.stmt);
                }
            }
        }
        if let Some((d, stmt)) = d {
            if reach.contains(&g.exit) {
                for o in &d.outputs {
                    if inn.defs_of(g.exit, &o.name).contains(&UNDEF) {
                        self.add_at(
                            "E021",
                            format!(
                                "output {} of @def {} is not set on every path",
                                str_repr(&o.name),
                                str_repr(&d.name)
                            ),
                            Some(stmt),
                        );
                    }
                }
                read_names.extend(d.outputs.iter().map(|o| o.name.clone()));
            }
        }
        let table: HashMap<&str, &Stmt> = namespaces
            .iter()
            .map(|ns| match &ns.kind {
                Kind::Namespace { label, .. } => (label.as_str(), *ns),
                _ => unreachable!("namespace"),
            })
            .collect();
        for s in &local {
            if let Kind::Parallel { labels } = &s.kind {
                self.parallel(s, labels, &table);
            }
        }
        if d.is_some() {
            // Top-level final values are the job's results.
            for s in &local {
                for name in s.writes() {
                    if !read_names.contains(name) {
                        self.add_at("W020", format!("{} is written but never read", str_repr(name)), Some(s));
                    }
                }
            }
        }
    }

    fn parallel(&mut self, s: &Stmt, labels: &[String], table: &HashMap<&str, &Stmt>) {
        let arms: Vec<(&str, &Vec<Stmt>)> = labels
            .iter()
            .filter_map(|l| table.get(l.as_str()))
            .map(|ns| match &ns.kind {
                Kind::Namespace { label, body } => (label.as_str(), body),
                _ => unreachable!("namespace"),
            })
            .collect();
        let collect = |body: &Vec<Stmt>, f: fn(&Stmt) -> Vec<&str>| -> BTreeSet<String> {
            walk(body).into_iter().flat_map(|x| f(x).into_iter().map(str::to_string).collect::<Vec<_>>()).collect()
        };
        let w: Vec<BTreeSet<String>> = arms.iter().map(|(_, b)| collect(b, Stmt::writes)).collect();
        let r: Vec<BTreeSet<String>> = arms.iter().map(|(_, b)| collect(b, Stmt::reads)).collect();
        for i in 0..arms.len() {
            for j in 0..arms.len() {
                if i == j {
                    continue;
                }
                let both: Vec<&String> = w[i].intersection(&w[j]).collect();
                if i < j && !both.is_empty() {
                    let msg = format!(
                        "parallel arms `{}` and `{}` both write {}",
                        arms[i].0,
                        arms[j].0,
                        str_list_repr(&both)
                    );
                    self.add_at("W010", msg, Some(s));
                }
                let crossed: Vec<&String> = w[i].intersection(&r[j]).collect();
                if !crossed.is_empty() {
                    let msg = format!(
                        "parallel arm `{}` reads {} written by `{}`",
                        arms[j].0,
                        str_list_repr(&crossed),
                        arms[i].0
                    );
                    self.add_at("W010", msg, Some(s));
                }
            }
        }
    }

    // ------------------------------------------------------------ calls and types
    fn call(&mut self, s: &Stmt, types: &HashMap<String, TypeExpr>) {
        let Kind::Call { name, args, outs } = &s.kind else { return };
        let r = match self.env.resolve(name) {
            Resolution::Unknown => {
                self.add_at("E010", format!("unknown node {}", str_repr(name)), Some(s));
                return;
            }
            Resolution::Reserved => return,
            Resolution::Ambiguous(what) => {
                self.add_at("E011", format!("node {} is {what}", str_repr(name)), Some(s));
                return;
            }
            Resolution::Found(r) => r,
        };
        let sig = &r.signature;
        let positional: Vec<&Expr> = args.iter().filter(|a| a.key.is_none()).map(|a| &a.value).collect();
        if positional.len() > sig.inputs.len() {
            self.add_at(
                "E012",
                format!("{name} takes {} inputs, {} given", sig.inputs.len(), positional.len()),
                Some(s),
            );
            return;
        }
        let mut bound: IndexMap<String, &Expr> = IndexMap::new();
        for (port, value) in sig.inputs.iter().zip(&positional) {
            bound.insert(port.name.clone(), value);
        }
        for a in args {
            let Some(key) = &a.key else { continue };
            if sig.input(key).is_none() {
                self.add_at("E012", format!("{name} has no input {}", str_repr(key)), Some(s));
            } else if bound.contains_key(key) {
                self.add_at("E012", format!("{name} input {} given twice", str_repr(key)), Some(s));
            } else {
                bound.insert(key.clone(), &a.value);
            }
        }
        for port in &sig.inputs {
            if port.required() && !bound.contains_key(&port.name) {
                self.add_at("E012", format!("{name} input {} is required", str_repr(&port.name)), Some(s));
            }
        }
        if outs.len() != sig.outputs.len() {
            self.add_at("E012", format!("{name} has {} outputs, {} bound", sig.outputs.len(), outs.len()), Some(s));
        }
        for (pname, value) in &bound {
            let port = sig.input(pname).expect("bound names are inputs");
            if let Some(t) = expr_type(value, types) {
                if !fits(Some(&t), Some(&port.ty)) {
                    let msg = format!(
                        "{name} input {} expects {}, got {}",
                        str_repr(pname),
                        type_text(Some(&port.ty)),
                        type_text(Some(&t))
                    );
                    self.add_at("E040", msg, Some(s));
                }
            }
        }
    }

    /// A name's type when every write of it in the scope agrees on one known type.
    fn name_types(&self, local: &[&Stmt], d: Option<&Def>) -> HashMap<String, TypeExpr> {
        let mut seen: IndexMap<String, HashSet<TypeExpr>> = IndexMap::new();
        let mut note = |name: &str, t: Option<TypeExpr>| {
            seen.entry(name.to_string()).or_default().insert(t.unwrap_or(TypeExpr::Any));
        };
        if let Some(d) = d {
            for p in &d.params {
                note(&p.name, p.ty.clone());
            }
        }
        for s in local {
            match &s.kind {
                Kind::Assign { target, value, ty } => {
                    let t = ty.clone().or_else(|| match value {
                        Expr::Literal(v) => Some(literal_type(v)),
                        Expr::Name(_) => None,
                    });
                    note(target, t);
                }
                Kind::Call { name, outs, .. } => {
                    let sig = self.env.resolve(name).found().map(|r| r.signature.into_owned());
                    let ports = sig.map(|s| s.outputs).unwrap_or_default();
                    for (i, o) in outs.iter().enumerate() {
                        if let Some(o) = o {
                            note(o, ports.get(i).map(|p| p.ty.clone()));
                        }
                    }
                }
                Kind::Each { item, index, .. } => {
                    for n in item.iter().chain(index.iter()) {
                        note(n, None);
                    }
                }
                Kind::Try { error_name: Some(e), .. } => note(e, Some(TypeExpr::name("dict"))),
                _ => {}
            }
        }
        seen.into_iter()
            .filter(|(_, ts)| ts.len() == 1 && !ts.contains(&TypeExpr::Any))
            .map(|(n, ts)| (n, ts.into_iter().next().expect("one type")))
            .collect()
    }
}

fn expr_type(e: &Expr, types: &HashMap<String, TypeExpr>) -> Option<TypeExpr> {
    match e {
        Expr::Literal(v) => Some(literal_type(v)),
        Expr::Name(n) => types.get(n).cloned(),
    }
}

/// All diagnostics for a program, errors and warnings, in source order.
pub fn check(program: &Program, env: &NodeEnv) -> Vec<Diagnostic> {
    let mut c = Checker { env, out: Vec::new() };
    let mut copy = program.clone();
    c.program(&mut copy);
    let mut out = c.out;
    out.sort_by(|a, b| {
        (a.line.unwrap_or(0), &a.code, &a.message, a.line).cmp(&(b.line.unwrap_or(0), &b.code, &b.message, b.line))
    });
    out.dedup();
    out
}
