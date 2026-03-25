//! Compiler passes for KohakuNodeIR.
//!
//! Passes:
//! - [`dataflow::compile_dataflow`]   — topologically sort dataflow statements.
//! - [`strip_meta::strip_meta`]       — remove `@meta` annotations (L2 → L3).
//! - [`type_check::type_check`]       — validate types against @typehint decls.
//! - [`dead_code::dead_code`]         — remove unused assignments.
//! - [`sanitizer::sanitize`]          — configurable L3 sanitizer.
//! - [`optimizer::optimize`]          — L4 optimizer (parallel, CSE, branch, DCE).

pub mod dataflow;
pub mod dead_code;
pub mod optimizer;
pub mod sanitizer;
pub mod strip_meta;
pub mod type_check;

#[cfg(feature = "pyo3")]
pub mod pyo3;

pub use dataflow::compile_dataflow;
pub use dead_code::dead_code;
pub use optimizer::optimize;
pub use sanitizer::{sanitize, SanitizerConfig};
pub use strip_meta::strip_meta;
pub use type_check::type_check;
