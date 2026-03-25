use pyo3::prelude::*;

use crate::ast::pyo3::register_ast_types;

/// Root Python module: `import kohakunode_rs`
#[pymodule]
fn kohakunode_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    register_ast_types(m)?;
    Ok(())
}
