//! KIR v2 (Kohaku Node IR) core: parser, canonical writer, signatures,
//! checker, optimization passes, program hashes and the graph view.
//!
//! The Python package `kohakunode` is the reference; every output here is
//! byte-identical to it (see `tests/golden.rs`).

pub mod api;
pub mod check;
pub mod compiler;
pub mod errors;
pub mod flow;
pub mod graph;
pub mod lower;
pub mod sig;
pub mod syntax;
pub mod util;

#[cfg(any(feature = "python", feature = "wasm"))]
mod bindings;

pub use errors::{KirError, Result};
