//! The KIR abstract syntax tree.
//!
//! Every statement carries `meta` (from `@meta`), `hint` (from `@hint`), the
//! source `line`, and a `uid` that identifies it inside one tree. Cloning a
//! tree keeps uids, so a cloned tree is a distinct identity space of its own;
//! a statement copied into the same tree gets fresh uids (`renew_uids`).

use std::sync::atomic::{AtomicUsize, Ordering};

use indexmap::IndexMap;

use crate::syntax::value::Value;

pub type Uid = usize;

static NEXT_UID: AtomicUsize = AtomicUsize::new(1);

pub fn fresh_uid() -> Uid {
    NEXT_UID.fetch_add(1, Ordering::Relaxed)
}

/// A type: `_`, a name, `T?`, `Name[T, ...]` or `A | B`.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum TypeExpr {
    Any,
    Name(String),
    Optional(Box<TypeExpr>),
    Generic(String, Vec<TypeExpr>),
    Union(Vec<TypeExpr>),
}

impl TypeExpr {
    pub fn name(n: &str) -> TypeExpr {
        TypeExpr::Name(n.to_string())
    }

    pub fn is_any(&self) -> bool {
        matches!(self, TypeExpr::Any)
    }
}

#[derive(Clone, Debug)]
pub enum Expr {
    Name(String),
    Literal(Value),
}

impl Expr {
    pub fn name(&self) -> Option<&str> {
        match self {
            Expr::Name(n) => Some(n),
            Expr::Literal(_) => None,
        }
    }
}

/// A call input: positional when `key` is None.
#[derive(Clone, Debug)]
pub struct Arg {
    pub value: Expr,
    pub key: Option<String>,
}

impl Arg {
    pub fn pos(value: Expr) -> Arg {
        Arg { value, key: None }
    }
}

/// `@meta` / `@hint` pairs in insertion order.
pub type Directives = IndexMap<String, Value>;

#[derive(Clone, Debug)]
pub struct Param {
    pub name: String,
    pub ty: Option<TypeExpr>,
    pub default: Option<Expr>,
}

#[derive(Clone, Debug)]
pub struct OutParam {
    pub name: String,
    pub ty: Option<TypeExpr>,
}

#[derive(Clone, Debug)]
pub struct Def {
    pub name: String,
    pub params: Vec<Param>,
    pub outputs: Vec<OutParam>,
    pub body: Vec<Stmt>,
}

#[derive(Clone, Debug)]
pub struct TypeHintEntry {
    pub name: String,
    pub inputs: Vec<TypeExpr>,
    pub outputs: Vec<TypeExpr>,
}

#[derive(Clone, Debug)]
pub enum Kind {
    Assign {
        target: String,
        value: Expr,
        ty: Option<TypeExpr>,
    },
    /// `(args)name(outs)`; an output of None is the discard `_`.
    Call {
        name: String,
        args: Vec<Arg>,
        outs: Vec<Option<String>>,
    },
    Branch {
        cond: Expr,
        true_label: String,
        false_label: String,
    },
    Switch {
        value: Expr,
        cases: Vec<(Value, String)>,
        default: Option<String>,
    },
    Jump {
        label: String,
    },
    Parallel {
        labels: Vec<String>,
    },
    /// `(items)each(item[, index], `label`)`; None outputs are `_`.
    Each {
        items: Expr,
        item: Option<String>,
        index: Option<String>,
        label: String,
        has_index: bool,
    },
    /// Snapshot items, sample `value` at normal body end, publish target only on completion.
    Collect {
        items: Expr,
        item: Option<String>,
        index: Option<String>,
        label: String,
        value: Expr,
        target: String,
        has_index: bool,
    },
    Namespace {
        label: String,
        body: Vec<Stmt>,
    },
    Dataflow {
        body: Vec<Stmt>,
    },
    Try {
        body: Vec<Stmt>,
        handler: Vec<Stmt>,
        error_name: Option<String>,
    },
    Def(Def),
    TypeHints {
        entries: Vec<TypeHintEntry>,
    },
}

#[derive(Clone, Debug)]
pub struct Stmt {
    pub uid: Uid,
    pub line: Option<usize>,
    pub meta: Directives,
    pub hint: Directives,
    pub origin: Option<Origin>,
    pub kind: Kind,
}

#[derive(Clone, Debug)]
pub struct Use {
    pub library: String,
    pub alias: Option<String>,
}

/// A source module import, distinct from a host signature `Use`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Import {
    pub module: String,
    pub alias: String,
}

/// Durable source identity, independent of editor metadata and semantic hashes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Origin {
    pub module: String,
    pub node_id: String,
    pub line: Option<num_bigint::BigInt>,
    pub definition: Option<String>,
    pub calls: Vec<Origin>,
    pub generated: Option<String>,
}

#[derive(Clone, Debug, Default)]
pub struct Program {
    pub uses: Vec<Use>,
    pub imports: Vec<Import>,
    pub exports: Vec<String>,
    pub body: Vec<Stmt>,
    pub mode: Option<String>,
}

pub const BUILTINS: [&str; 6] = ["branch", "switch", "jump", "parallel", "each", "collect"];

impl Stmt {
    pub fn new(kind: Kind, line: Option<usize>) -> Stmt {
        Stmt { uid: fresh_uid(), line, meta: Directives::new(), hint: Directives::new(), origin: None, kind }
    }

    pub fn assign(target: impl Into<String>, value: Expr, line: Option<usize>) -> Stmt {
        Stmt::new(Kind::Assign { target: target.into(), value, ty: None }, line)
    }

    pub fn call(name: &str, args: Vec<Arg>, outs: Vec<Option<String>>, line: Option<usize>) -> Stmt {
        Stmt::new(Kind::Call { name: name.to_string(), args, outs }, line)
    }

    /// Assignments and calls.
    pub fn is_simple(&self) -> bool {
        matches!(self.kind, Kind::Assign { .. } | Kind::Call { .. })
    }

    /// The nested statement lists, in order.
    pub fn children(&self) -> Vec<&Vec<Stmt>> {
        match &self.kind {
            Kind::Namespace { body, .. } | Kind::Dataflow { body } => vec![body],
            Kind::Def(d) => vec![&d.body],
            Kind::Try { body, handler, .. } => vec![body, handler],
            _ => vec![],
        }
    }

    pub fn children_mut(&mut self) -> Vec<&mut Vec<Stmt>> {
        match &mut self.kind {
            Kind::Namespace { body, .. } | Kind::Dataflow { body } => vec![body],
            Kind::Def(d) => vec![&mut d.body],
            Kind::Try { body, handler, .. } => vec![body, handler],
            _ => vec![],
        }
    }

    /// The namespace labels a builtin statement names.
    pub fn labels_entered(&self) -> Vec<&str> {
        match &self.kind {
            Kind::Branch { true_label, false_label, .. } => vec![true_label, false_label],
            Kind::Switch { cases, default, .. } => {
                cases.iter().map(|(_, l)| l.as_str()).chain(default.as_deref()).collect()
            }
            Kind::Jump { label } | Kind::Each { label, .. } | Kind::Collect { label, .. } => vec![label],
            Kind::Parallel { labels } => labels.iter().map(String::as_str).collect(),
            _ => vec![],
        }
    }

    /// Names a simple or builtin statement reads.
    pub fn reads(&self) -> Vec<&str> {
        match &self.kind {
            Kind::Assign { value: Expr::Name(n), .. } => vec![n],
            Kind::Call { args, .. } => args.iter().filter_map(|a| a.value.name()).collect(),
            Kind::Branch { cond: Expr::Name(n), .. }
            | Kind::Switch { value: Expr::Name(n), .. }
            | Kind::Each { items: Expr::Name(n), .. }
            | Kind::Collect { items: Expr::Name(n), .. } => vec![n],
            _ => vec![],
        }
    }

    /// Names sampled only after a collect body completes normally.
    pub fn deferred_reads(&self) -> Vec<&str> {
        match &self.kind {
            Kind::Collect { value: Expr::Name(name), .. } => vec![name],
            _ => vec![],
        }
    }

    /// Names a simple or builtin statement writes.
    pub fn writes(&self) -> Vec<&str> {
        match &self.kind {
            Kind::Assign { target, .. } => vec![target],
            Kind::Call { outs, .. } => outs.iter().filter_map(|o| o.as_deref()).collect(),
            Kind::Each { item, index, .. } => item.as_deref().into_iter().chain(index.as_deref()).collect(),
            Kind::Collect { item, index, target, .. } => {
                item.as_deref().into_iter().chain(index.as_deref()).chain(std::iter::once(target.as_str())).collect()
            }
            _ => vec![],
        }
    }

    /// Give this statement and every nested one a fresh uid.
    pub fn renew_uids(&mut self) {
        self.uid = fresh_uid();
        for body in self.children_mut() {
            for s in body {
                s.renew_uids();
            }
        }
    }
}

/// Every statement, depth first, including nested bodies.
pub fn walk(stmts: &[Stmt]) -> Vec<&Stmt> {
    fn go<'a>(stmts: &'a [Stmt], out: &mut Vec<&'a Stmt>) {
        for s in stmts {
            out.push(s);
            for body in s.children() {
                go(body, out);
            }
        }
    }
    let mut out = Vec::new();
    go(stmts, &mut out);
    out
}

/// Apply `f` to every statement, depth first, including nested bodies.
pub fn walk_mut(stmts: &mut [Stmt], f: &mut dyn FnMut(&mut Stmt)) {
    for s in stmts {
        f(s);
        for body in s.children_mut() {
            walk_mut(body, f);
        }
    }
}
