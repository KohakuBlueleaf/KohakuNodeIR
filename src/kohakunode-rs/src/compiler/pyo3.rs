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

/// Python binding for `type_check`.
#[pyfunction(name = "type_check")]
pub fn py_type_check(program_json: &str) -> PyResult<String> {
    let program: Program = serde_json::from_str(program_json)
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;
    let result = crate::compiler::type_check::type_check(&program)
        .map_err(|e| PyValueError::new_err(e))?;
    serde_json::to_string(&result)
        .map_err(|e| PyValueError::new_err(format!("JSON serialise error: {e}")))
}

/// Python binding for `eliminate_dead_code`.
#[pyfunction(name = "eliminate_dead_code")]
pub fn py_dead_code(program_json: &str) -> PyResult<String> {
    let program: Program = serde_json::from_str(program_json)
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;
    let result = crate::compiler::dead_code::dead_code(&program);
    serde_json::to_string(&result)
        .map_err(|e| PyValueError::new_err(format!("JSON serialise error: {e}")))
}

/// Python binding for `optimize`.
///
/// Accepts a JSON Program and an optional JSON list of pass names.
/// Returns the optimized JSON Program.
#[pyfunction(name = "optimize")]
pub fn py_optimize(program_json: &str, passes_json: Option<&str>) -> PyResult<String> {
    let program: Program = serde_json::from_str(program_json)
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;
    let passes: Option<Vec<String>> = passes_json
        .map(|s| serde_json::from_str(s))
        .transpose()
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;
    let pass_strs: Option<Vec<&str>> = passes.as_ref().map(|v| v.iter().map(|s| s.as_str()).collect());
    let result = crate::compiler::optimizer::optimize(&program, pass_strs.as_deref())
        .map_err(|e| PyValueError::new_err(e))?;
    serde_json::to_string(&result)
        .map_err(|e| PyValueError::new_err(format!("JSON serialise error: {e}")))
}

/// Python binding for `sanitize`.
#[pyfunction(name = "sanitize")]
pub fn py_sanitize(
    program_json: &str,
    strip_meta: Option<bool>,
    resolve_dataflow: Option<bool>,
    type_check: Option<bool>,
    remove_dead_code: Option<bool>,
) -> PyResult<String> {
    let program: Program = serde_json::from_str(program_json)
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;
    let config = crate::compiler::sanitizer::SanitizerConfig {
        strip_meta: strip_meta.unwrap_or(true),
        resolve_dataflow: resolve_dataflow.unwrap_or(true),
        type_check: type_check.unwrap_or(true),
        remove_dead_code: remove_dead_code.unwrap_or(true),
    };
    let result = crate::compiler::sanitizer::sanitize(&program, &config)
        .map_err(|e| PyValueError::new_err(e))?;
    serde_json::to_string(&result)
        .map_err(|e| PyValueError::new_err(format!("JSON serialise error: {e}")))
}

/// Register compiler functions into the Python module.
pub fn register_compiler_fns(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_compile_dataflow, m)?)?;
    m.add_function(wrap_pyfunction!(py_strip_meta, m)?)?;
    m.add_function(wrap_pyfunction!(py_type_check, m)?)?;
    m.add_function(wrap_pyfunction!(py_dead_code, m)?)?;
    m.add_function(wrap_pyfunction!(py_optimize, m)?)?;
    m.add_function(wrap_pyfunction!(py_sanitize, m)?)?;
    Ok(())
}
