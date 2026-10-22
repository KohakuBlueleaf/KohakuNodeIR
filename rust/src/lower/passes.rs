//! Optimization passes (passes.md): each rewrites a program into a simpler
//! program in the same language. `lower` runs them all, giving the most
//! directly interpretable form: no `@def`, no `each`, every name versioned,
//! straight runs grouped in `@dataflow:` blocks.

use std::collections::HashSet;

use sha2::{Digest, Sha256};

use crate::errors::{KirError, Result};
use crate::flow::order::sort_dataflow;
use crate::lower::each::EachExpander;
use crate::lower::inline::Inliner;
use crate::lower::versions::version_program;
use crate::origins::derive_origin;
use crate::sig::env::NodeEnv;
use crate::syntax::ast::{walk_mut, Kind, Program, Stmt};
use crate::syntax::writer::write;
use crate::util::pyfmt::{str_list_repr, str_repr};

/// The passes in their run order.
pub const PASSES: [&str; 6] = ["order_dataflow", "inline", "expand_each", "version", "group", "strip_meta"];

/// Passes that must have run earlier in the same list.
fn requires(name: &str) -> &'static [&'static str] {
    match name {
        "inline" => &["order_dataflow"],
        "version" => &["order_dataflow", "inline", "expand_each"],
        _ => &[],
    }
}

/// Put every `@dataflow:` block in stable data order; apply `@mode dataflow`.
fn order_dataflow(p: &mut Program, env: &NodeEnv) -> Result<()> {
    let is_ordered = |s: &Stmt| match &s.kind {
        Kind::Call { name, .. } => env.is_ordered(name),
        _ => false,
    };
    sort_dataflow(p, &is_ordered).map_err(|_| KirError::Value("dependency cycle in @dataflow block".into()))?;
    p.mode = None;
    Ok(())
}

/// Wrap straight runs in `@dataflow:` blocks (typehints first).
fn group(p: &mut Program) {
    let (hints, rest): (Vec<Stmt>, Vec<Stmt>) =
        std::mem::take(&mut p.body).into_iter().partition(|s| matches!(s.kind, Kind::TypeHints { .. }));
    p.body = hints;
    p.body.extend(group_block(rest));
}

/// Wrap straight runs of assignments and calls in `@dataflow:` blocks, splitting
/// a run before a statement that writes a name an earlier statement of it reads.
fn group_block(stmts: Vec<Stmt>) -> Vec<Stmt> {
    let mut flat = Vec::with_capacity(stmts.len());
    for s in stmts {
        match s.kind {
            Kind::Dataflow { body } => flat.extend(body),
            _ => flat.push(s),
        }
    }
    let mut out = Vec::new();
    let mut run: Vec<Stmt> = Vec::new();
    let mut read: HashSet<String> = HashSet::new();
    for mut s in flat {
        if s.is_simple() {
            if s.writes().iter().any(|w| read.contains(*w)) {
                out.push(group_run(std::mem::take(&mut run)));
                read.clear();
            }
            read.extend(s.reads().into_iter().map(str::to_string));
            run.push(s);
            continue;
        }
        if !run.is_empty() {
            out.push(group_run(std::mem::take(&mut run)));
            read.clear();
        }
        for body in s.children_mut() {
            *body = group_block(std::mem::take(body));
        }
        out.push(s);
    }
    if !run.is_empty() {
        out.push(group_run(run));
    }
    out
}

fn group_run(body: Vec<Stmt>) -> Stmt {
    let origin = derive_origin(body.iter().find_map(|s| s.origin.as_ref()), Some("group"), &[]);
    let mut stmt = Stmt::new(Kind::Dataflow { body }, None);
    stmt.origin = origin;
    stmt
}

fn run_pass(name: &str, p: &mut Program, env: &NodeEnv) -> Result<()> {
    match name {
        "order_dataflow" => order_dataflow(p, env)?,
        "inline" => p.body = Inliner::new(p).block(std::mem::take(&mut p.body)),
        "expand_each" => p.body = EachExpander::default().block(std::mem::take(&mut p.body)),
        "version" => version_program(p)?,
        "group" => group(p),
        "strip_meta" => walk_mut(&mut p.body, &mut |s| s.meta.clear()),
        _ => unreachable!("validated pass names"),
    }
    Ok(())
}

/// A rewritten copy of a checked program after the named passes (default: all, in order).
pub fn run_passes(program: &Program, env: &NodeEnv, names: Option<&[&str]>) -> Result<Program> {
    let names: Vec<&str> = names.map_or(PASSES.to_vec(), <[&str]>::to_vec);
    for (i, name) in names.iter().enumerate() {
        let missing: Vec<&str> = requires(name).iter().copied().filter(|r| !names[..i].contains(r)).collect();
        if !missing.is_empty() {
            return Err(KirError::Value(format!(
                "pass {} needs {} before it",
                str_repr(name),
                str_list_repr(&missing)
            )));
        }
        if !PASSES.contains(name) {
            return Err(KirError::Value(format!("unknown pass {}", str_repr(name))));
        }
    }
    let mut p = program.clone();
    for name in names {
        run_pass(name, &mut p, env)?;
    }
    Ok(p)
}

/// Every pass: the most directly interpretable form of a checked program.
pub fn lower(program: &Program, env: &NodeEnv) -> Result<Program> {
    run_passes(program, env, None)
}

fn sha256_hex(text: &str) -> String {
    Sha256::digest(text.as_bytes()).iter().map(|b| format!("{b:02x}")).collect()
}

/// SHA-256 of the canonical text without `@meta` or `@hint`.
pub fn semantic_hash(p: &Program) -> Result<String> {
    let mut q = p.clone();
    walk_mut(&mut q.body, &mut |s| {
        s.hint.clear();
        s.meta.clear();
    });
    Ok(sha256_hex(&write(&q)?))
}

/// SHA-256 of the canonical text without `@meta` (hints included).
pub fn full_hash(p: &Program) -> Result<String> {
    let mut q = p.clone();
    walk_mut(&mut q.body, &mut |s| s.meta.clear());
    Ok(sha256_hex(&write(&q)?))
}
