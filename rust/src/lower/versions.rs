//! The `version` pass: every write gets its own version (passes.md).
//!
//! A read reached by one write reads that write's version `x__n`. A name read
//! somewhere with several writes reaching it gets a home version `x__0`: each
//! of its writes is followed by `x__0 = x__n` and those reads read `x__0`.

use std::collections::{HashMap, HashSet};

use crate::errors::{KirError, Result};
use crate::flow::cfg::{build_cfg, reaching, UNDEF};
use crate::origins::derive_origin;
use crate::syntax::ast::{walk, Expr, Kind, Program, Stmt, Uid};
use crate::util::pyfmt::str_repr;

fn home(name: &str) -> String {
    format!("{name}__0")
}

struct Versions {
    node_of: HashMap<Uid, usize>,
    binds: HashMap<Uid, usize>,
    version: HashMap<(usize, String), String>,
    read_map: HashMap<(usize, String), String>,
    homes: HashSet<String>,
}

impl Versions {
    fn read(&self, n: Option<usize>, e: &mut Expr) {
        if let Expr::Name(x) = e {
            let v = n.and_then(|n| self.read_map.get(&(n, x.clone())));
            *x = v.cloned().unwrap_or_else(|| home(x));
        }
    }

    fn write(&self, n: Option<usize>, name: &str) -> Result<String> {
        n.and_then(|n| self.version.get(&(n, name.to_string())))
            .cloned()
            .ok_or_else(|| KirError::Value(format!("KeyError: (None, {})", str_repr(name))))
    }

    fn rewrite(&self, stmts: Vec<Stmt>) -> Result<Vec<Stmt>> {
        let mut out = Vec::with_capacity(stmts.len());
        for mut s in stmts {
            let n = self.node_of.get(&s.uid).copied();
            let mut copies = Vec::new();
            let mut handler_copy = None;
            let line = s.line;
            match &mut s.kind {
                Kind::Assign { target, value, .. } => {
                    self.read(n, value);
                    let old = std::mem::take(target);
                    *target = self.write(n, &old)?;
                    if self.homes.contains(&old) {
                        copies.push(Stmt::assign(home(&old), Expr::Name(target.clone()), line));
                    }
                }
                Kind::Call { args, outs, .. } => {
                    for a in args.iter_mut() {
                        self.read(n, &mut a.value);
                    }
                    for o in outs.iter_mut() {
                        if let Some(old) = o.take() {
                            let new = self.write(n, &old)?;
                            if self.homes.contains(&old) {
                                copies.push(Stmt::assign(home(&old), Expr::Name(new.clone()), line));
                            }
                            *o = Some(new);
                        }
                    }
                }
                Kind::Branch { cond, .. } => self.read(n, cond),
                Kind::Switch { value, .. } => self.read(n, value),
                Kind::Try { error_name: Some(e), .. } => {
                    let old = e.clone();
                    let bind = self.binds[&s.uid];
                    *e = self.version[&(bind, old.clone())].clone();
                    if self.homes.contains(&old) {
                        handler_copy = Some(Stmt::assign(home(&old), Expr::Name(e.clone()), line));
                    }
                }
                _ => {}
            }
            for body in s.children_mut() {
                *body = self.rewrite(std::mem::take(body))?;
            }
            for copy in &mut copies {
                copy.origin = derive_origin(s.origin.as_ref(), Some("version.home"), &[]);
            }
            if let Some(copy) = &mut handler_copy {
                copy.origin = derive_origin(s.origin.as_ref(), Some("version.handler"), &[]);
            }
            // Added after the handler is rewritten: the copy is already versioned.
            if let (Some(copy), Kind::Try { handler, .. }) = (handler_copy, &mut s.kind) {
                handler.insert(0, copy);
            }
            out.push(s);
            out.extend(copies);
        }
        Ok(out)
    }
}

/// Version every write of the top-level scope in place.
pub fn version_program(program: &mut Program) -> Result<()> {
    let v = {
        let g = build_cfg(&program.body, &[]);
        let inn = reaching(&g, &[]);
        let mut counters: HashMap<&str, usize> = HashMap::new();
        let mut version = HashMap::new();
        for s in walk(&program.body) {
            let Some(&n) = g.binds.get(&s.uid).or_else(|| g.node_of.get(&s.uid)) else { continue };
            for name in &g.nodes[n].writes {
                let c = counters.entry(name).or_insert(0);
                *c += 1;
                version.insert((n, name.clone()), format!("{name}__{c}"));
            }
        }
        let mut read_map = HashMap::new();
        let mut homes = HashSet::new();
        for n in g.reachable() {
            for name in &g.nodes[n].reads {
                let mut ds = inn.defs_of(n, name);
                ds.remove(&UNDEF);
                let target = if ds.len() == 1 {
                    let d = *ds.iter().next().expect("one def") as usize;
                    version[&(d, name.clone())].clone()
                } else {
                    homes.insert(name.clone());
                    home(name)
                };
                read_map.insert((n, name.clone()), target);
            }
        }
        Versions { node_of: g.node_of, binds: g.binds, version, read_map, homes }
    };
    let body = std::mem::take(&mut program.body);
    program.body = v.rewrite(body)?;
    Ok(())
}
