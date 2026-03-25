//! PyO3 stubs for the KirGraph compiler.
//!
//! Uses a JSON bridge — accepts a KirGraph JSON string, returns a Program JSON
//! string — matching the pattern used in `compiler::pyo3` and `serializer::pyo3`.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::kirgraph::{compiler, KirGraph};

/// Compile a KirGraph JSON string (L1) to a KIR Program JSON string (L2).
///
/// # Errors
/// Raises `ValueError` on JSON parse failure.
#[pyfunction(name = "compile_kirgraph")]
pub fn py_compile_kirgraph(kirgraph_json: &str) -> PyResult<String> {
    let graph: KirGraph = KirGraph::from_json(kirgraph_json)
        .map_err(|e| PyValueError::new_err(format!("KirGraph JSON parse error: {e}")))?;

    let program = compiler::compile(&graph);

    serde_json::to_string(&program)
        .map_err(|e| PyValueError::new_err(format!("Program JSON serialize error: {e}")))
}

/// Register kirgraph functions into the Python module.
pub fn register_kirgraph_fns(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_compile_kirgraph, m)?)?;
    Ok(())
}
