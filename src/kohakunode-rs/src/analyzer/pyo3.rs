//! PyO3 stub for the analyzer module.
//!
//! Full Python bindings will be wired up in Phase 8 (Python integration).
//! For now this file just ensures the module compiles under `--features pyo3`.

use pyo3::prelude::*;

/// Register analyzer symbols into the Python module.
///
/// Currently a no-op placeholder; will expose `validate` as a Python
/// callable once the AST PyO3 wrappers are complete.
pub fn register_analyzer(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Placeholder — nothing to register yet.
    let _ = m;
    Ok(())
}
