//! Compiler passes for KohakuNodeIR.
//!
//! Current passes:
//! - [`dataflow::compile_dataflow`] — topologically sort dataflow statements.
//! - [`strip_meta::strip_meta`] — remove `@meta` annotations (L2 → L3).

pub mod dataflow;
pub mod strip_meta;

#[cfg(feature = "pyo3")]
pub mod pyo3;

pub use dataflow::compile_dataflow;
pub use strip_meta::strip_meta;
