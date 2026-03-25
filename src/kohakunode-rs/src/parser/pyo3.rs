//! PyO3 wrapper for the KIR parser.
//!
//! Exposed as `kohakunode_rs.parse_kir(text: str) -> str` from Python.
//! Returns a JSON-serialised `Program` AST on success, or raises a
//! `ValueError` on parse failure.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Parse KIR source text and return the AST as a JSON string.
///
/// Raises `ValueError` if parsing fails.
#[pyfunction]
pub fn parse_kir(text: &str) -> PyResult<String> {
    let program =
        super::parse(text).map_err(|e| PyValueError::new_err(format!("KIR parse error: {e}")))?;
    let json = serde_json::to_string(&program)
        .map_err(|e| PyValueError::new_err(format!("JSON serialization error: {e}")))?;
    Ok(json)
}

/// Register parser functions into the Python module.
pub fn register_parser_fns(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_kir, m)?)?;
    Ok(())
}
