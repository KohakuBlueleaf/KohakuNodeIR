//! The extension module `kohakunode._rs`.

use std::path::PathBuf;

use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;

use crate::api;
use crate::errors::KirError as CoreError;

create_exception!(kohakunode._rs, KirError, PyException, "Base class for every KIR error.");
create_exception!(kohakunode._rs, KirSyntaxError, KirError);
create_exception!(kohakunode._rs, KirCheckError, KirError);
create_exception!(kohakunode._rs, KirSignatureError, KirError);
create_exception!(kohakunode._rs, KirGraphError, KirError);

fn py_err(e: CoreError) -> PyErr {
    let msg = e.to_string();
    match e {
        CoreError::Syntax { .. } => KirSyntaxError::new_err(msg),
        CoreError::Check(_) => KirCheckError::new_err(msg),
        CoreError::Signature(_) => KirSignatureError::new_err(msg),
        CoreError::Graph(_) => KirGraphError::new_err(msg),
        CoreError::Value(_) => PyValueError::new_err(msg),
    }
}

/// The AST of `source` as JSON text.
#[pyfunction]
fn parse_to_json(source: &str) -> PyResult<String> {
    api::parse_to_json(source).map_err(py_err)
}

/// Canonical text of `source`.
#[pyfunction]
fn format(source: &str) -> PyResult<String> {
    api::format(source).map_err(py_err)
}

/// `@use` resolution inputs: the program's directory and the signature search path.
struct Where {
    base: Option<String>,
    sig_path: Vec<String>,
}

impl Where {
    fn new(base: Option<PathBuf>, sig_path: Vec<PathBuf>) -> Where {
        let text = |p: PathBuf| p.to_string_lossy().into_owned();
        Where { base: base.map(text), sig_path: sig_path.into_iter().map(text).collect() }
    }

    fn with<'a>(&'a self, texts: &'a [String]) -> api::Signatures<'a> {
        api::Signatures { texts, base: self.base.as_deref(), sig_path: &self.sig_path }
    }
}

/// Diagnostics of `source` as a JSON list; `sigs` are `.kirsig.json` texts, `base`
/// the program's directory and `sig_path` the directories searched for `@use`.
#[pyfunction]
#[pyo3(signature = (source, sigs = Vec::new(), *, base = None, sig_path = Vec::new()))]
fn check(source: &str, sigs: Vec<String>, base: Option<PathBuf>, sig_path: Vec<PathBuf>) -> PyResult<String> {
    api::check(source, Where::new(base, sig_path).with(&sigs)).map_err(py_err)
}

/// Canonical text of a checked program after the named passes (default: all).
#[pyfunction]
#[pyo3(signature = (source, sigs = Vec::new(), passes = None, *, base = None, sig_path = Vec::new()))]
fn lower(
    source: &str,
    sigs: Vec<String>,
    passes: Option<Vec<String>>,
    base: Option<PathBuf>,
    sig_path: Vec<PathBuf>,
) -> PyResult<String> {
    api::lower(source, Where::new(base, sig_path).with(&sigs), passes.as_deref()).map_err(py_err)
}

/// `{"semantic", "full"}` hashes of the program after the passes, as JSON text.
#[pyfunction]
#[pyo3(signature = (source, sigs = Vec::new(), passes = None, *, base = None, sig_path = Vec::new()))]
fn hashes(
    source: &str,
    sigs: Vec<String>,
    passes: Option<Vec<String>>,
    base: Option<PathBuf>,
    sig_path: Vec<PathBuf>,
) -> PyResult<String> {
    api::hashes(source, Where::new(base, sig_path).with(&sigs), passes.as_deref()).map_err(py_err)
}

/// The `.kirgraph` JSON text of `source`; `data` is `"wires"` or `"variables"`.
#[pyfunction]
#[pyo3(signature = (source, sigs = Vec::new(), data = "wires", *, base = None, sig_path = Vec::new()))]
fn to_graph(
    source: &str,
    sigs: Vec<String>,
    data: &str,
    base: Option<PathBuf>,
    sig_path: Vec<PathBuf>,
) -> PyResult<String> {
    api::to_graph(source, Where::new(base, sig_path).with(&sigs), data).map_err(py_err)
}

/// Canonical text of a `.kirgraph` JSON document.
#[pyfunction]
#[pyo3(signature = (graph, with_meta = true))]
fn from_graph(graph: &str, with_meta: bool) -> PyResult<String> {
    api::from_graph(graph, with_meta).map_err(py_err)
}

/// The `kir.std` signature file text.
#[pyfunction]
fn std_signatures() -> PyResult<String> {
    api::std_signatures().map_err(py_err)
}

#[pymodule]
#[pyo3(name = "_rs")]
fn kohakunode_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_to_json, m)?)?;
    m.add_function(wrap_pyfunction!(format, m)?)?;
    m.add_function(wrap_pyfunction!(check, m)?)?;
    m.add_function(wrap_pyfunction!(lower, m)?)?;
    m.add_function(wrap_pyfunction!(hashes, m)?)?;
    m.add_function(wrap_pyfunction!(to_graph, m)?)?;
    m.add_function(wrap_pyfunction!(from_graph, m)?)?;
    m.add_function(wrap_pyfunction!(std_signatures, m)?)?;
    let py = m.py();
    m.add("KirError", py.get_type::<KirError>())?;
    m.add("KirSyntaxError", py.get_type::<KirSyntaxError>())?;
    m.add("KirCheckError", py.get_type::<KirCheckError>())?;
    m.add("KirSignatureError", py.get_type::<KirSignatureError>())?;
    m.add("KirGraphError", py.get_type::<KirGraphError>())?;
    Ok(())
}
