//! Resolve the node names a program calls (signatures.md, "`@use`").

use std::borrow::Cow;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use indexmap::IndexMap;

use crate::errors::Result;
use crate::sig::files::{load_library, resolve_library, sig_path};
use crate::sig::model::{Library, Port, Signature};
use crate::sig::std::{internal_library, std_library};
use crate::syntax::ast::{walk, Def, Expr, Kind, Program, TypeExpr};

/// What a node name refers to: a library signature or a `@def`.
pub struct Resolved<'a> {
    pub signature: Cow<'a, Signature>,
    pub library: Option<&'a Library>,
    pub definition: Option<&'a Def>,
}

pub enum Resolution<'a> {
    Found(Resolved<'a>),
    Unknown,
    /// A `kir.` internal node in a program as written.
    Reserved,
    /// Several unaliased libraries define the name; holds `"ambiguous: a, b"`.
    Ambiguous(String),
}

impl<'a> Resolution<'a> {
    pub fn found(self) -> Option<Resolved<'a>> {
        match self {
            Resolution::Found(r) => Some(r),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct NodeEnv {
    pub libraries: Vec<(Arc<Library>, Option<String>)>,
    pub defs: IndexMap<String, Def>,
    pub typehints: IndexMap<String, Signature>,
    pub internal: bool,
}

impl NodeEnv {
    pub fn resolve(&self, name: &str) -> Resolution<'_> {
        if let Some(d) = self.defs.get(name) {
            return Resolution::Found(Resolved {
                signature: Cow::Owned(def_signature(d)),
                library: None,
                definition: Some(d),
            });
        }
        let internal = internal_library();
        if name.starts_with("kir.") && internal.contains(name) {
            if !self.internal {
                return Resolution::Reserved;
            }
            return found(internal, name);
        }
        let (head, rest) = name.split_once('.').unwrap_or((name, ""));
        for (lib, alias) in &self.libraries {
            if alias.as_deref() == Some(head) && lib.contains(rest) {
                return found(lib, rest);
            }
        }
        let hits: Vec<&Arc<Library>> =
            self.libraries.iter().filter(|(l, a)| a.is_none() && l.contains(name)).map(|(l, _)| l).collect();
        if hits.len() > 1 {
            let names: Vec<&str> = hits.iter().map(|l| l.name.as_str()).collect();
            return Resolution::Ambiguous(format!("ambiguous: {}", names.join(", ")));
        }
        if let Some(lib) = hits.first() {
            return found(lib, name);
        }
        if let Some(sig) = self.typehints.get(name) {
            return Resolution::Found(Resolved { signature: Cow::Borrowed(sig), library: None, definition: None });
        }
        if std_library().contains(name) {
            return found(std_library(), name);
        }
        Resolution::Unknown
    }

    /// Whether `name` resolves to a signature marked `ordered`.
    pub fn is_ordered(&self, name: &str) -> bool {
        self.resolve(name).found().is_some_and(|r| r.signature.ordered)
    }
}

fn found<'a>(lib: &'a Library, node: &str) -> Resolution<'a> {
    Resolution::Found(Resolved {
        signature: Cow::Borrowed(&lib.signatures[node]),
        library: Some(lib),
        definition: None,
    })
}

pub fn def_signature(d: &Def) -> Signature {
    let inputs = d
        .params
        .iter()
        .map(|p| Port {
            name: p.name.clone(),
            ty: p.ty.clone().unwrap_or(TypeExpr::Any),
            default: p.default.as_ref().map(|e| match e {
                Expr::Literal(v) => v.clone(),
                Expr::Name(_) => crate::syntax::value::Value::None,
            }),
        })
        .collect();
    let outputs = d.outputs.iter().map(|o| Port::new(&o.name, o.ty.clone().unwrap_or(TypeExpr::Any))).collect();
    Signature::new(&d.name, inputs, outputs)
}

/// The node environment of a program.
///
/// `libraries` are extra libraries given directly (unaliased); `@use`
/// entries are resolved against them first by name, then on the signature
/// path.
pub fn build_env(
    program: &Program,
    libraries: &[Arc<Library>],
    base_dir: Option<&Path>,
    search: &[PathBuf],
    internal: bool,
) -> Result<NodeEnv> {
    let mut env = NodeEnv { internal, ..NodeEnv::default() };
    let mut used = HashSet::new();
    for u in &program.uses {
        let lib = match libraries.iter().rev().find(|l| l.name == u.library) {
            Some(l) => l.clone(),
            None if u.library == std_library().name => Arc::new(std_library().clone()),
            None => Arc::new(load_library(&resolve_library(&u.library, base_dir, &sig_path(search))?)?),
        };
        used.insert(lib.name.clone());
        env.libraries.push((lib, u.alias.clone()));
    }
    for lib in libraries {
        if !used.contains(&lib.name) {
            env.libraries.push((lib.clone(), None));
        }
    }
    for s in walk(&program.body) {
        match &s.kind {
            Kind::Def(d) => {
                env.defs.insert(d.name.clone(), d.clone());
            }
            Kind::TypeHints { entries } => {
                for e in entries {
                    let ports = |ts: &[TypeExpr], p: &str| {
                        ts.iter().enumerate().map(|(i, t)| Port::new(format!("{p}{i}"), t.clone())).collect()
                    };
                    env.typehints.insert(
                        e.name.clone(),
                        Signature::new(&e.name, ports(&e.inputs, "in"), ports(&e.outputs, "out")),
                    );
                }
            }
            _ => {}
        }
    }
    Ok(env)
}
