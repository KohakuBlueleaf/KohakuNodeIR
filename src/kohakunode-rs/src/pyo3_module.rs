use pyo3::prelude::*;

use crate::ast::pyo3::register_ast_types;
use crate::compiler::pyo3::register_compiler_fns;
use crate::kirgraph::pyo3::register_kirgraph_fns;

/// Root Python module: `import kohakunode_rs`
#[pymodule]
fn kohakunode_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    register_ast_types(m)?;
    register_compiler_fns(m)?;
    register_kirgraph_fns(m)?;
    Ok(())
}
