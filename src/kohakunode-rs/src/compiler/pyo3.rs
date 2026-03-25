//! PyO3 stubs for the compiler passes.
//!
//! Exposes `compile_dataflow` and `strip_meta` as Python callables.
//! The JSON round-trip avoids the need for full `#[pyclass]` wrappers
//! on every AST type — matching the pattern used elsewhere in this crate.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::ast::Program;

/// Python binding for `compile_dataflow`.
///
/// Accepts and returns a JSON-serialised `Program` string so that Python
/// code can call this without bespoke PyO3 class wrappers for every AST node.
///
/// # Errors
/// Raises `ValueError` on a dependency cycle or control-flow in dataflow mode.
#[pyfunction(name = "compile_dataflow")]
pub fn py_compile_dataflow(program_json: &str) -> PyResult<String> {
    let program: Program = serde_json::from_str(program_json)
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;

    let result = crate::compiler::dataflow::compile_dataflow(&program)
        .map_err(|e| PyValueError::new_err(e))?;

    serde_json::to_string(&result)
        .map_err(|e| PyValueError::new_err(format!("JSON serialise error: {e}")))
}

/// Python binding for `strip_meta`.
///
/// Accepts and returns a JSON-serialised `Program` string.
#[pyfunction(name = "strip_meta")]
pub fn py_strip_meta(program_json: &str) -> PyResult<String> {
    let program: Program = serde_json::from_str(program_json)
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;

    let result = crate::compiler::strip_meta::strip_meta(&program);

    serde_json::to_string(&result)
        .map_err(|e| PyValueError::new_err(format!("JSON serialise error: {e}")))
}

/// Register compiler functions into the Python module.
pub fn register_compiler_fns(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_compile_dataflow, m)?)?;
    m.add_function(wrap_pyfunction!(py_strip_meta, m)?)?;
    Ok(())
}
