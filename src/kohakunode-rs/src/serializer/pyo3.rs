//! PyO3 bindings for the KIR serializer.
//!
//! Exposes [`write_from_json`] as `kohakunode_rs.serializer.write(program_json)`.

use pyo3::prelude::*;

use crate::ast::Program;

/// Deserialize a JSON-encoded [`Program`] AST and return KIR source text.
///
/// # Arguments
/// * `program_json` — JSON string produced by serializing a [`Program`] with serde_json.
///
/// # Errors
/// Returns a `ValueError` if the JSON cannot be parsed as a valid [`Program`].
#[pyfunction]
pub fn write(program_json: &str) -> PyResult<String> {
    let program: Program = serde_json::from_str(program_json).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!(
            "Failed to parse Program JSON: {}",
            e
        ))
    })?;
    Ok(super::write(&program))
}

/// Register serializer functions into the Python module.
pub fn register_serializer(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(write, m)?)?;
    Ok(())
}
