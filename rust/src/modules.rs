//! Deterministic source-module linking, before checking and lowering.
//! Source maps are authoritative; importing a module never executes its body.
use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use indexmap::IndexMap;
use sha2::{Digest, Sha256};

use crate::errors::{KirError, Result};
use crate::lower::semantic_hash;
use crate::origins::stamp_origins;
use crate::sig::env::{build_env, build_env_with_record_validation, NodeEnv, Resolution};
use crate::sig::files::library_to_json;
use crate::sig::model::Library;
use crate::sig::std::{std_library, std_library_arc};
use crate::syntax::ast::{walk, Def, Kind, Program, Stmt, TypeExpr, Use};
use crate::syntax::parse;
use crate::util::json::Json;
use crate::util::pyfmt::str_repr;

pub type ModuleMap = BTreeMap<String, String>;

pub struct Linked {
    pub program: Program,
    pub libraries: Vec<Arc<Library>>,
    pub dependencies: Json,
}

#[derive(Clone)]
struct Module {
    name: String,
    program: Program,
    env: NodeEnv,
    imports: BTreeMap<String, String>,
    definitions: BTreeMap<String, Def>,
}

fn error(message: impl Into<String>) -> KirError {
    KirError::Signature(message.into())
}
pub(crate) fn sha256(text: &str) -> String {
    Sha256::digest(text.as_bytes()).iter().map(|b| format!("{b:02x}")).collect()
}
fn prefix(module: &str) -> String {
    format!("_kir_{}__", &sha256(module)[..16])
}

/// Compact sorted-key JSON, matching Python's dependency identity encoding.
fn canonical(value: &Json) -> String {
    match value {
        Json::Object(pairs) => {
            let mut pairs: Vec<_> = pairs.iter().collect();
            pairs.sort_by(|a, b| a.0.cmp(&b.0));
            format!(
                "{{{}}}",
                pairs
                    .iter()
                    .map(|(k, v)| format!("{}:{}", Json::str(k).dumps(), canonical(v)))
                    .collect::<Vec<_>>()
                    .join(",")
            )
        }
        Json::Array(items) => format!("[{}]", items.iter().map(canonical).collect::<Vec<_>>().join(",")),
        _ => value.dumps(),
    }
}

/// Portable signature identity excludes documentation and node declaration order.
pub fn contract_hash(lib: &Library) -> Result<String> {
    fn portable(value: &crate::syntax::value::Value) -> std::result::Result<(), &'static str> {
        use crate::syntax::value::Value;
        match value {
            Value::Dict(pairs) => {
                if pairs.iter().any(|(k, _)| !matches!(k, Value::Str(_))) {
                    return Err("default object keys must be strings");
                }
                pairs.iter().try_for_each(|(_, v)| portable(v))
            }
            Value::List(items) => items.iter().try_for_each(portable),
            Value::Tuple(_) => Err("default 'tuple' is not portable JSON data"),
            Value::Float(f) if !f.is_finite() => Err("default floats must be finite"),
            _ => Ok(()),
        }
    }
    for sig in lib.signatures.values() {
        for port in &sig.inputs {
            if let Some(value) = &port.default {
                portable(value).map_err(|why| {
                    error(format!("library {} has a nonportable signature default: {why}", str_repr(&lib.name)))
                })?;
            }
        }
    }
    let mut contract = library_to_json(lib)?;
    if let Some(Json::Array(nodes)) = contract.get_mut("nodes") {
        for node in nodes.iter_mut() {
            if let Json::Object(pairs) = node {
                pairs.retain(|(k, _)| k != "doc");
            }
        }
        nodes.sort_by(|a, b| a.get("name").and_then(Json::as_str).cmp(&b.get("name").and_then(Json::as_str)));
    }
    if let Some(Json::Array(records)) = contract.get_mut("records") {
        records.sort_by(|a, b| a.get("name").and_then(Json::as_str).cmp(&b.get("name").and_then(Json::as_str)));
    }
    Ok(sha256(&canonical(&contract)))
}

/// Normalize portable resource IDs without consulting a filesystem.
pub fn module_id(request: &str, importer: &str) -> Result<String> {
    if request.is_empty() || request.contains(['\\', ':']) || request.starts_with('/') {
        return Err(error(format!("invalid module resource {}: use a relative POSIX path", str_repr(request))));
    }
    let parent = importer.rsplit_once('/').map_or("", |(p, _)| p);
    let joined = if parent.is_empty() { request.to_string() } else { format!("{parent}/{request}") };
    let mut parts = Vec::new();
    for part in joined.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if parts.pop().is_none() {
                    return Err(error(format!("module resource {} escapes the package root", str_repr(request))));
                }
            }
            _ => parts.push(part),
        }
    }
    if parts.is_empty() {
        return Err(error(format!("module resource {} escapes the package root", str_repr(request))));
    }
    Ok(parts.join("/"))
}

fn type_names(ty: &TypeExpr, names: &mut HashSet<String>) {
    match ty {
        TypeExpr::Any => {}
        TypeExpr::Name(n) => {
            names.insert(n.clone());
        }
        TypeExpr::Optional(t) => type_names(t, names),
        TypeExpr::Generic(n, args) => {
            names.insert(n.clone());
            for t in args {
                type_names(t, names);
            }
        }
        TypeExpr::Union(args) => {
            for t in args {
                type_names(t, names);
            }
        }
    }
}
fn host_types(module: &Module) -> HashSet<String> {
    let mut names = HashSet::new();
    for (lib, _) in &module.env.libraries {
        for sig in lib.signatures.values() {
            for p in sig.inputs.iter().chain(&sig.outputs) {
                type_names(&p.ty, &mut names);
            }
        }
    }
    names
}
fn builtin(name: &str) -> bool {
    matches!(
        name,
        "bool" | "int" | "float" | "str" | "None" | "list" | "dict" | "tuple" | "set" | "bytes" | "object" | "complex"
    )
}
fn public_types(module: &Module) -> HashSet<String> {
    let mut names = HashSet::new();
    for name in &module.program.exports {
        let def = &module.definitions[name];
        for ty in
            def.params.iter().filter_map(|p| p.ty.as_ref()).chain(def.outputs.iter().filter_map(|p| p.ty.as_ref()))
        {
            type_names(ty, &mut names);
        }
    }
    names
}

struct Linker<'a> {
    libraries: &'a [Arc<Library>],
    base: Option<&'a Path>,
    search: &'a [PathBuf],
    sources: Option<&'a ModuleMap>,
    root: String,
    loaded: BTreeMap<String, Module>,
    active: Vec<String>,
    active_files: Vec<PathBuf>,
    uses: Vec<Use>,
    hosts: IndexMap<String, Arc<Library>>,
}

impl Linker<'_> {
    fn read(&self, name: &str) -> Result<String> {
        if let Some(sources) = self.sources {
            return sources
                .get(name)
                .cloned()
                .ok_or_else(|| error(format!("module {} is missing from the module map", str_repr(name))));
        }
        let base = self
            .base
            .ok_or_else(|| error(format!("module {} needs a module map or a base directory", str_repr(name))))?;
        let root = base.canonicalize().map_err(|e| error(format!("cannot read module {}: {e}", str_repr(name))))?;
        let path =
            root.join(name).canonicalize().map_err(|e| error(format!("cannot read module {}: {e}", str_repr(name))))?;
        if !path.starts_with(&root) {
            return Err(error(format!("module {} resolves outside the package root", str_repr(name))));
        }
        std::fs::read_to_string(path).map_err(|e| error(format!("cannot read module {}: {e}", str_repr(name))))
    }

    fn visit(&mut self, name: &str, program: Option<Program>) -> Result<()> {
        if self.active.iter().any(|n| n == name) {
            let mut chain = self.active.clone();
            chain.push(name.into());
            return Err(error(format!("import cycle: {}", chain.join(" -> "))));
        }
        if self.loaded.contains_key(name) {
            return Ok(());
        }
        let physical = if self.sources.is_none() && name != "<text>" {
            self.base.and_then(|base| base.join(name).canonicalize().ok())
        } else {
            None
        };
        if let Some(path) = &physical {
            if self.active_files.contains(path) {
                let mut chain = self.active.clone();
                chain.push(name.into());
                return Err(error(format!("import cycle: {}", chain.join(" -> "))));
            }
            self.active_files.push(path.clone());
        }
        self.active.push(name.into());
        let result = self.visit_inner(name, program).map_err(|e| {
            let message = e.to_string();
            if message.starts_with("import chain ") {
                e
            } else {
                error(format!("import chain {}: {message}", self.active.join(" -> ")))
            }
        });
        self.active.pop();
        if physical.is_some() {
            self.active_files.pop();
        }
        result
    }

    fn visit_inner(&mut self, name: &str, program: Option<Program>) -> Result<()> {
        let program = match program {
            Some(p) => p,
            None => parse(&self.read(name)?)?,
        };
        let program = stamp_origins(&program, name);
        if name != self.root
            && (program.mode.is_some()
                || program.body.iter().any(|s| !matches!(s.kind, Kind::Def(_) | Kind::TypeHints { .. })))
        {
            return Err(error("imported modules contain declarations only"));
        }
        let mut definitions = BTreeMap::new();
        for s in walk(&program.body) {
            let mut names = s.reads();
            names.extend(s.deferred_reads());
            names.extend(s.writes());
            names.extend(s.labels_entered());
            match &s.kind {
                Kind::Def(d) => {
                    names.push(&d.name);
                    names.extend(d.params.iter().map(|p| p.name.as_str()));
                    names.extend(d.outputs.iter().map(|p| p.name.as_str()));
                }
                Kind::Namespace { label, .. } => names.push(label),
                Kind::TypeHints { entries } => names.extend(entries.iter().map(|e| e.name.as_str())),
                Kind::Call { name, .. } => names.push(name),
                Kind::Try { error_name: Some(name), .. } => names.push(name),
                _ => {}
            }
            if names.iter().any(|n| n.starts_with("_kir_")) {
                return Err(error("authored names cannot use reserved prefix '_kir_'"));
            }
            if let Kind::Def(d) = &s.kind {
                if d.name.starts_with("_kir_") || definitions.contains_key(&d.name) {
                    return Err(error(format!("duplicate or reserved definition {}", str_repr(&d.name))));
                }
                definitions.insert(d.name.clone(), d.clone());
            }
        }
        let top: HashSet<_> = program
            .body
            .iter()
            .filter_map(|s| match &s.kind {
                Kind::Def(d) => Some(d.name.as_str()),
                _ => None,
            })
            .collect();
        let mut exports = HashSet::new();
        for export in &program.exports {
            if !exports.insert(export) {
                return Err(error(format!("duplicate export {}", str_repr(export))));
            }
            if !top.contains(export.as_str()) {
                return Err(error(format!("export {} is not a top-level definition", str_repr(export))));
            }
        }
        let parent = name.rsplit_once('/').map_or("", |(p, _)| p);
        let base = self.base.map(|b| b.join(parent));
        let env =
            build_env_with_record_validation(&program, self.libraries, base.as_deref(), self.search, false, false)?;
        let aliases: HashSet<_> = program.uses.iter().filter_map(|u| u.alias.as_deref()).collect();
        if aliases.iter().any(|a| a.starts_with("_kir_")) {
            return Err(error("signature aliases cannot use reserved prefix '_kir_'"));
        }
        let mut imports = BTreeMap::new();
        for import in &program.imports {
            if import.alias.starts_with("_kir_") {
                return Err(error("import aliases cannot use reserved prefix '_kir_'"));
            }
            if imports.contains_key(&import.alias)
                || aliases.contains(import.alias.as_str())
                || definitions.contains_key(&import.alias)
            {
                return Err(error(format!("ambiguous import alias {}", str_repr(&import.alias))));
            }
            let target = module_id(&import.module, name)?;
            imports.insert(import.alias.clone(), target.clone());
            self.visit(&target, None)?;
        }
        self.loaded.insert(name.into(), Module { name: name.into(), program, env, imports, definitions });
        Ok(())
    }

    fn definition_name(&self, module: &Module, name: &str) -> String {
        if module.name == self.root {
            name.into()
        } else {
            prefix(&module.name) + name
        }
    }

    fn host_aliases(&mut self, module: &Module) -> Result<BTreeMap<usize, String>> {
        let mut aliases = BTreeMap::new();
        let mut libraries = module.env.libraries.clone();
        let standard = std_library_arc();
        if module.name != self.root && !libraries.iter().any(|(l, _)| Arc::ptr_eq(l, &standard)) {
            libraries.push((standard.clone(), None));
        }
        for (i, (lib, original_alias)) in libraries.iter().enumerate() {
            if let Some(existing) = self.hosts.get(&lib.name) {
                if contract_hash(existing)? != contract_hash(lib)? {
                    return Err(error(format!("incompatible signature libraries share name {}", str_repr(&lib.name))));
                }
            } else {
                self.hosts.insert(lib.name.clone(), lib.clone());
            }
            let alias = format!("{}lib{i}", prefix(&module.name));
            aliases.insert(Arc::as_ptr(lib) as usize, alias.clone());
            if Arc::ptr_eq(lib, &standard) {
                aliases.insert(std_library() as *const Library as usize, alias.clone());
            }
            if module.name != self.root {
                self.uses.push(Use { library: lib.name.clone(), alias: Some(alias) });
            } else if original_alias.is_none()
                && !self.uses[..module.program.uses.len()].iter().any(|u| u.library == lib.name)
            {
                self.uses.push(Use { library: lib.name.clone(), alias: None });
            }
        }
        Ok(aliases)
    }

    fn type_name(&self, module: &Module, name: &str) -> Result<String> {
        if name.starts_with("_kir_") {
            return Err(error("authored types cannot use reserved prefix '_kir_'"));
        }
        if let Some((head, rest)) = name.split_once('.') {
            if let Some(target) = module.imports.get(head).map(|id| &self.loaded[id]) {
                if !public_types(target).contains(rest) {
                    return Err(error(format!("{}: type {} is not public", module.name, str_repr(name))));
                }
                return self.type_name(target, rest);
            }
        }
        let record_type = module.env.record_type(&TypeExpr::name(name))?;
        if let TypeExpr::Name(canonical) = record_type {
            if canonical != name {
                return Ok(canonical);
            }
        }
        Ok(if name.is_empty() || builtin(name) || host_types(module).contains(name) {
            name.into()
        } else {
            prefix(&module.name) + name
        })
    }

    fn rewrite_type(&self, module: &Module, ty: &mut TypeExpr) -> Result<()> {
        let name = |n: &str| self.type_name(module, n);
        match ty {
            TypeExpr::Any => {}
            TypeExpr::Name(n) => *n = name(n)?,
            TypeExpr::Optional(t) => self.rewrite_type(module, t)?,
            TypeExpr::Generic(n, args) => {
                *n = name(n)?;
                for t in args {
                    self.rewrite_type(module, t)?;
                }
            }
            TypeExpr::Union(args) => {
                for t in args {
                    self.rewrite_type(module, t)?;
                }
            }
        }
        Ok(())
    }

    fn rewrite_block(&self, module: &Module, aliases: &BTreeMap<usize, String>, body: &mut [Stmt]) -> Result<()> {
        for stmt in body {
            match &mut stmt.kind {
                Kind::Def(d) => {
                    d.name = self.definition_name(module, &d.name);
                    for ty in d
                        .params
                        .iter_mut()
                        .filter_map(|p| p.ty.as_mut())
                        .chain(d.outputs.iter_mut().filter_map(|p| p.ty.as_mut()))
                    {
                        self.rewrite_type(module, ty)?;
                    }
                }
                Kind::Assign { ty: Some(ty), .. } => self.rewrite_type(module, ty)?,
                Kind::TypeHints { entries } => {
                    for entry in entries {
                        if module.name != self.root {
                            entry.name = prefix(&module.name) + "hint." + &entry.name;
                        }
                        for ty in entry.inputs.iter_mut().chain(&mut entry.outputs) {
                            self.rewrite_type(module, ty)?;
                        }
                    }
                }
                Kind::Call { name, .. } => {
                    let target = name
                        .split_once('.')
                        .and_then(|(head, rest)| module.imports.get(head).map(|id| (&self.loaded[id], rest)));
                    if let Some((target, rest)) = target {
                        if !target.program.exports.iter().any(|e| e == rest) {
                            return Err(error(format!(
                                "{}:{}: {} is not exported by {}",
                                module.name,
                                stmt.line.map_or("None".into(), |n| n.to_string()),
                                str_repr(name),
                                str_repr(&target.name)
                            )));
                        }
                        *name = self.definition_name(target, rest);
                    } else if module.definitions.contains_key(name) {
                        *name = self.definition_name(module, name);
                    } else {
                        let resolved = match module.env.resolve(name) {
                            Resolution::Found(r) => r,
                            other => {
                                let reason = match other {
                                    Resolution::Reserved => "reserved".into(),
                                    Resolution::Ambiguous(s) => s,
                                    _ => "unknown".into(),
                                };
                                return Err(error(format!(
                                    "{}:{}: node {} is {reason}",
                                    module.name,
                                    stmt.line.map_or("None".into(), |n| n.to_string()),
                                    str_repr(name)
                                )));
                            }
                        };
                        if module.name != self.root {
                            if let Some(lib) = resolved.library {
                                if let Some(alias) = aliases.get(&(lib as *const Library as usize)) {
                                    *name = format!("{alias}.{}", resolved.signature.name);
                                }
                            } else if module.env.typehints.contains_key(name) {
                                *name = prefix(&module.name) + "hint." + name;
                            }
                        }
                    }
                }
                _ => {}
            }
            for child in stmt.children_mut() {
                self.rewrite_block(module, aliases, child)?;
            }
        }
        Ok(())
    }

    fn rewrite(&mut self, module: &Module) -> Result<Vec<Stmt>> {
        let mut body = module.program.body.clone();
        let aliases = self.host_aliases(module)?;
        self.rewrite_block(module, &aliases, &mut body)?;
        Ok(body)
    }

    fn portable_uses(module: &Module) -> Vec<Use> {
        module
            .program
            .uses
            .iter()
            .zip(&module.env.libraries)
            .map(|(u, (lib, _))| Use { library: lib.name.clone(), alias: u.alias.clone() })
            .collect()
    }

    fn manifest(&self) -> Result<Json> {
        let modules = self
            .loaded
            .iter()
            .map(|(name, module)| {
                let mut source = module.program.clone();
                source.uses = Self::portable_uses(module);
                let mut exports = module.program.exports.clone();
                exports.sort();
                Ok(Json::Object(vec![
                    ("module".into(), Json::str(name)),
                    ("semantic_hash".into(), Json::str(semantic_hash(&source)?)),
                    (
                        "imports".into(),
                        Json::Object(module.imports.iter().map(|(k, v)| (k.clone(), Json::str(v))).collect()),
                    ),
                    ("exports".into(), Json::strs(&exports)),
                ]))
            })
            .collect::<Result<Vec<_>>>()?;
        let mut hosts: Vec<_> = self.hosts.iter().collect();
        hosts.sort_by_key(|(name, _)| *name);
        let mut signatures = Vec::new();
        for (name, lib) in hosts {
            signatures.push(Json::Object(vec![
                ("library".into(), Json::str(name)),
                ("hash".into(), Json::str(contract_hash(lib)?)),
            ]));
        }
        let mut identity = Json::Object(vec![
            ("version".into(), Json::int(1)),
            ("modules".into(), Json::Array(modules)),
            ("signatures".into(), Json::Array(signatures)),
        ]);
        identity.insert("hash", Json::str(sha256(&canonical(&identity))));
        Ok(identity)
    }
}

/// Link source declarations. A supplied map is authoritative, including an empty
/// map; without one, relative resources may be loaded beneath `base_dir`.
pub fn link_program(
    program: &Program,
    libraries: &[Arc<Library>],
    base_dir: Option<&Path>,
    search: &[PathBuf],
    modules: Option<&ModuleMap>,
    source_name: &str,
) -> Result<Linked> {
    let root = if source_name == "<text>" { source_name.into() } else { module_id(source_name, "")? };
    if program.imports.is_empty() && program.exports.is_empty() {
        let mut result = stamp_origins(program, &root);
        let env = build_env(&result, libraries, base_dir, search, false)?;
        if !env.record_schemas()?.is_empty() {
            let resolved: IndexMap<String, Arc<Library>> =
                env.libraries.iter().map(|(lib, _)| (lib.name.clone(), lib.clone())).collect();
            let mut sorted: Vec<_> = resolved.iter().collect();
            sorted.sort_by_key(|(name, _)| *name);
            let signatures = sorted
                .into_iter()
                .map(|(name, lib)| {
                    Ok(Json::Object(vec![
                        ("library".into(), Json::str(name)),
                        ("hash".into(), Json::str(contract_hash(lib)?)),
                    ]))
                })
                .collect::<Result<Vec<_>>>()?;
            let mut dependencies = Json::Object(vec![
                ("version".into(), Json::int(1)),
                ("modules".into(), Json::Array(vec![])),
                ("signatures".into(), Json::Array(signatures)),
            ]);
            dependencies.insert("hash", Json::str(sha256(&canonical(&dependencies))));
            result.uses = result
                .uses
                .iter()
                .zip(&env.libraries)
                .map(|(u, (lib, _))| Use { library: lib.name.clone(), alias: u.alias.clone() })
                .collect();
            return Ok(Linked { program: result, libraries: resolved.into_values().collect(), dependencies });
        }
        return Ok(Linked { program: result, libraries: libraries.to_vec(), dependencies: Json::Object(vec![]) });
    }
    let mut linker = Linker {
        libraries,
        base: base_dir,
        search,
        sources: modules,
        root: root.clone(),
        loaded: BTreeMap::new(),
        active: vec![],
        active_files: vec![],
        uses: vec![],
        hosts: IndexMap::new(),
    };
    linker.visit(&root, Some(program.clone()))?;
    let entry = linker.loaded[&root].clone();
    linker.uses = Linker::portable_uses(&entry);
    let mut body = Vec::new();
    let dependencies: Vec<_> = linker.loaded.values().filter(|m| m.name != root).cloned().collect();
    for module in dependencies {
        body.extend(linker.rewrite(&module)?);
    }
    body.extend(linker.rewrite(&entry)?);
    let program = Program { uses: linker.uses.clone(), body, mode: entry.program.mode, ..Program::default() };
    let libraries: Vec<_> = linker.hosts.values().cloned().collect();
    build_env(&program, &libraries, base_dir, search, false)?;
    let dependencies = linker.manifest()?;
    Ok(Linked { program, libraries, dependencies })
}
