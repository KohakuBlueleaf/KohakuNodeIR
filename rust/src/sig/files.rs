//! Signature files (`<library>.kirsig.json`) and `@use` resolution.

use std::path::{Path, PathBuf};

use crate::errors::{KirError, Result};
use crate::sig::model::{Library, Port, Signature};
use crate::sig::types::{parse_type, type_text};
use crate::syntax::ast::TypeExpr;
use crate::syntax::value::Value;
use crate::util::json::{self, Json};
use crate::util::pyfmt::{path_str, str_list_repr, str_repr};

pub const SUFFIX: &str = ".kirsig.json";
pub const FORMAT: i64 = 1;

fn sig_err(m: impl Into<String>) -> KirError {
    KirError::Signature(m.into())
}

/// A malformed signature document: the reference's `KeyError` / `ValueError`,
/// which `load_library` reports as "cannot load signature file".
fn bad(m: impl Into<String>) -> KirError {
    KirError::Value(m.into())
}

fn key<'a>(obj: &'a Json, k: &str) -> Result<&'a Json> {
    obj.get(k).ok_or_else(|| bad(str_repr(k)))
}

fn string<'a>(obj: &'a Json, k: &str) -> Result<&'a str> {
    key(obj, k)?.as_str().ok_or_else(|| bad(format!("{} must be a string", str_repr(k))))
}

pub fn library_to_json(lib: &Library) -> Result<Json> {
    let mut nodes = Vec::with_capacity(lib.signatures.len());
    for sig in lib.signatures.values() {
        let mut entry = Json::Object(vec![
            ("name".into(), Json::str(&sig.name)),
            ("inputs".into(), Json::Array(sig.inputs.iter().map(|p| port_json(p, true)).collect::<Result<_>>()?)),
            ("outputs".into(), Json::Array(sig.outputs.iter().map(|p| port_json(p, false)).collect::<Result<_>>()?)),
        ]);
        if !sig.mutates.is_empty() || sig.ordered {
            entry.insert(
                "flags",
                Json::Object(vec![
                    ("mutates".into(), Json::strs(&sig.mutates)),
                    ("ordered".into(), Json::Bool(sig.ordered)),
                ]),
            );
        }
        if !sig.doc.is_empty() {
            entry.insert("doc", Json::str(&sig.doc));
        }
        nodes.push(entry);
    }
    Ok(Json::Object(vec![
        ("kirsig".into(), Json::int(FORMAT)),
        ("library".into(), Json::str(&lib.name)),
        ("nodes".into(), Json::Array(nodes)),
    ]))
}

fn port_json(p: &Port, with_default: bool) -> Result<Json> {
    let mut out = Json::Object(vec![("name".into(), Json::str(&p.name))]);
    if p.ty != TypeExpr::Any {
        out.insert("type", Json::str(type_text(Some(&p.ty))));
    }
    if let (true, Some(default)) = (with_default, &p.default) {
        let v = default.to_json().map_err(|e| sig_err(format!("default of {} is not JSON: {e}", str_repr(&p.name))))?;
        out.insert("default", v);
    }
    Ok(out)
}

pub fn library_from_json(data: &Json) -> Result<Library> {
    let format = data.get("kirsig").map_or(Value::None, Value::from_json);
    if !format.py_eq(&Value::int(FORMAT)) {
        return Err(sig_err(format!("unsupported signature format {}", format.repr())));
    }
    let mut lib = Library::new(string(data, "library")?);
    let nodes = key(data, "nodes")?.as_array().ok_or_else(|| bad("'nodes' must be a list"))?;
    for entry in nodes {
        let empty = Json::Object(vec![]);
        let flags = entry.get("flags").unwrap_or(&empty);
        let mutates = match flags.get("mutates") {
            None => vec![],
            Some(m) => m
                .as_array()
                .ok_or_else(|| bad("'mutates' must be a list"))?
                .iter()
                .map(|x| x.as_str().map(str::to_string).ok_or_else(|| bad("'mutates' holds names")))
                .collect::<Result<_>>()?,
        };
        let ports = |k: &str, with_default: bool| -> Result<Vec<Port>> {
            match entry.get(k) {
                None => Ok(vec![]),
                Some(list) => list
                    .as_array()
                    .ok_or_else(|| bad(format!("{} must be a list", str_repr(k))))?
                    .iter()
                    .map(|p| port_from(p, with_default))
                    .collect(),
            }
        };
        lib.add_signature(Signature {
            name: string(entry, "name")?.to_string(),
            inputs: ports("inputs", true)?,
            outputs: ports("outputs", false)?,
            mutates,
            ordered: flags.get("ordered").is_some_and(Json::truthy),
            doc: match entry.get("doc") {
                None => String::new(),
                Some(d) => d.as_str().ok_or_else(|| bad("'doc' must be a string"))?.to_string(),
            },
        })?;
    }
    Ok(lib)
}

fn port_from(p: &Json, with_default: bool) -> Result<Port> {
    let ty = match p.get("type") {
        None => TypeExpr::Any,
        Some(t) => parse_type(t.as_str().ok_or_else(|| bad("'type' must be a string"))?).map_err(bad)?,
    };
    let default = if with_default { p.get("default").map(Value::from_json) } else { None };
    Ok(Port { name: string(p, "name")?.to_string(), ty, default })
}

/// A library from the text of a `.kirsig.json` file.
pub fn library_from_text(text: &str) -> Result<Library> {
    library_from_json(&json::loads(text).map_err(bad)?)
}

pub fn save_library(lib: &Library, path: &Path) -> Result<()> {
    let text = library_to_json(lib)?.dumps_indent(2) + "\n";
    std::fs::write(path, text).map_err(|e| sig_err(format!("cannot write {}: {e}", path.display())))
}

/// A signature file; malformed content is "cannot load signature file <path>: <reason>".
pub fn load_library(path: &Path) -> Result<Library> {
    let shown = path_str(&path.to_string_lossy());
    let text =
        std::fs::read_to_string(path).map_err(|e| sig_err(format!("cannot load signature file {shown}: {e}")))?;
    library_from_text(&text).map_err(|e| match e {
        KirError::Value(m) => sig_err(format!("cannot load signature file {shown}: {m}")),
        other => other,
    })
}

/// The signature search path: `extra` first, then `KIR_SIG_PATH`.
pub fn sig_path(extra: &[PathBuf]) -> Vec<PathBuf> {
    let mut dirs = extra.to_vec();
    if let Ok(env) = std::env::var("KIR_SIG_PATH") {
        let sep = if cfg!(windows) { ';' } else { ':' };
        dirs.extend(env.split(sep).filter(|p| !p.is_empty()).map(PathBuf::from));
    }
    dirs
}

/// Find the signature file for a `@use` string (signatures.md, "Resolution").
pub fn resolve_library(name: &str, base_dir: Option<&Path>, search: &[PathBuf]) -> Result<PathBuf> {
    if name.ends_with(SUFFIX) {
        let mut p = PathBuf::from(name);
        if !p.is_absolute() {
            if let Some(base) = base_dir {
                p = base.join(p);
            }
        }
        if p.is_file() {
            return Ok(p);
        }
        return Err(sig_err(format!("signature file {} not found", str_repr(name))));
    }
    for d in search {
        let p = d.join(format!("{name}{SUFFIX}"));
        if p.is_file() {
            return Ok(p);
        }
    }
    let dirs: Vec<String> = search.iter().map(|d| path_str(&d.to_string_lossy())).collect();
    Err(sig_err(format!("library {} not found on the signature path {}", str_repr(name), str_list_repr(&dirs))))
}
