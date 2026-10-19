//! Optimization passes and program hashes.

pub mod each;
pub mod inline;
pub mod passes;
pub mod versions;

pub use passes::{full_hash, lower, run_passes, semantic_hash, PASSES};
