pub mod ast;

pub mod serializer;

pub mod compiler;

pub mod parser;

pub mod kirgraph;

// Placeholder modules — implemented in later phases
// pub mod layout;
pub mod analyzer;

#[cfg(feature = "pyo3")]
mod pyo3_module;
