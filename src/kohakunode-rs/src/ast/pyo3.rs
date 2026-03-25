//! PyO3 wrappers for AST types.
//!
//! Exposes Rust AST types to Python as classes.
//! This is a thin wrapper — the real types live in `types.rs`.

use pyo3::prelude::*;

/// Register all AST types into the Python module.
pub fn register_ast_types(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Placeholder — will add #[pyclass] wrappers in Phase 8 (Python integration)
    // For now, just make sure the module compiles.
    m.add("__ast_version__", "0.1.0")?;
    Ok(())
}
