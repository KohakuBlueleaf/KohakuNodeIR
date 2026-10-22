//! Resolve the node names a program calls (signatures.md, "`@use`").

use std::borrow::Cow;
use std::collections::{BTreeSet, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use indexmap::IndexMap;

use crate::errors::{KirError, Result};
use crate::sig::files::{load_library, resolve_library, sig_path};
use crate::sig::model::{Library, Port, Signature};
use crate::sig::records::{nominal_references, validate_record_cycles, RecordSchema};
use crate::sig::std::{internal_library, std_library, std_library_arc};
use crate::syntax::ast::{walk, Def, Expr, Kind, Program, Stmt, TypeExpr};
use crate::util::pyfmt::str_repr;

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

    /// Canonical records available through any alias. Conflicting identities fail.
    pub fn record_schemas(&self) -> Result<IndexMap<String, &RecordSchema>> {
        let mut records: IndexMap<String, &RecordSchema> = IndexMap::new();
        for (library, _) in &self.libraries {
            for schema in library.records.values() {
                if records.get(schema.schema_id()).is_some_and(|prior| !prior.same_schema(schema)) {
                    return Err(KirError::Signature(format!(
                        "conflicting record schema {}",
                        str_repr(schema.schema_id())
                    )));
                }
                records.insert(schema.schema_id().into(), schema);
            }
        }
        Ok(records)
    }

    pub fn record_type(&self, ty: &TypeExpr) -> Result<TypeExpr> {
        Ok(match ty {
            TypeExpr::Name(name) => {
                let records = self.record_schemas()?;
                if records.contains_key(name) {
                    return Ok(ty.clone());
                }
                let qualified = name.split_once('.');
                let mut hits = BTreeSet::new();
                for (library, alias) in &self.libraries {
                    for (local, schema) in &library.records {
                        if (alias.is_none() && name == local)
                            || qualified.is_some_and(|(head, rest)| alias.as_deref() == Some(head) && rest == local)
                        {
                            hits.insert(schema.schema_id().to_string());
                        }
                    }
                }
                if hits.len() > 1 {
                    return Err(KirError::Signature(format!(
                        "ambiguous record type {}: {}",
                        str_repr(name),
                        hits.into_iter().collect::<Vec<_>>().join(", ")
                    )));
                }
                TypeExpr::Name(hits.into_iter().next().unwrap_or_else(|| name.clone()))
            }
            TypeExpr::Optional(inner) => TypeExpr::Optional(Box::new(self.record_type(inner)?)),
            TypeExpr::Generic(name, parts) => {
                TypeExpr::Generic(name.clone(), parts.iter().map(|p| self.record_type(p)).collect::<Result<_>>()?)
            }
            TypeExpr::Union(parts) => {
                TypeExpr::Union(parts.iter().map(|p| self.record_type(p)).collect::<Result<_>>()?)
            }
            TypeExpr::Any => TypeExpr::Any,
        })
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
    build_env_with_record_validation(program, libraries, base_dir, search, internal, true)
}

/// Source linking assembles the transitive schema closure before checking references.
pub(crate) fn build_env_with_record_validation(
    program: &Program,
    libraries: &[Arc<Library>],
    base_dir: Option<&Path>,
    search: &[PathBuf],
    internal: bool,
    validate_records: bool,
) -> Result<NodeEnv> {
    let mut env = NodeEnv { internal, ..NodeEnv::default() };
    let mut used = HashSet::new();
    for u in &program.uses {
        let lib = match libraries.iter().rev().find(|l| l.name == u.library) {
            Some(l) => l.clone(),
            None if u.library == std_library().name => std_library_arc(),
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
    let records = env.record_schemas()?;
    if validate_records {
        for schema in records.values() {
            for field in schema.fields() {
                for reference in nominal_references(field.ty()) {
                    if !records.contains_key(&reference) {
                        return Err(KirError::Signature(format!(
                            "record {} field {} references unknown schema {}",
                            str_repr(schema.schema_id()),
                            str_repr(field.name()),
                            str_repr(&reference)
                        )));
                    }
                }
            }
        }
        validate_record_cycles(records.values().copied()).map_err(|e| KirError::Signature(e.to_string()))?;
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

/// Return a copy with record annotations canonicalized, retaining authored text separately.
pub fn qualify_record_types(program: &Program, env: &NodeEnv) -> Result<Program> {
    fn block(stmts: &mut [Stmt], env: &NodeEnv) -> Result<()> {
        for stmt in stmts {
            match &mut stmt.kind {
                Kind::Def(d) => {
                    for ty in d
                        .params
                        .iter_mut()
                        .filter_map(|p| p.ty.as_mut())
                        .chain(d.outputs.iter_mut().filter_map(|p| p.ty.as_mut()))
                    {
                        *ty = env.record_type(ty)?;
                    }
                }
                Kind::Assign { ty: Some(ty), .. } => *ty = env.record_type(ty)?,
                Kind::TypeHints { entries } => {
                    for entry in entries {
                        for ty in entry.inputs.iter_mut().chain(&mut entry.outputs) {
                            *ty = env.record_type(ty)?;
                        }
                    }
                }
                _ => {}
            }
            for children in stmt.children_mut() {
                block(children, env)?;
            }
        }
        Ok(())
    }
    let mut result = program.clone();
    block(&mut result.body, env)?;
    Ok(result)
}
