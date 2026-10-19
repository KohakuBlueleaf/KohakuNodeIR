//! One call from a parsed program to a checked program, its optimized form and hashes.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::check::{check, Diagnostic};
use crate::errors::{KirError, Result};
use crate::lower::{full_hash, run_passes, semantic_hash};
use crate::sig::env::{build_env, NodeEnv};
use crate::sig::model::Library;
use crate::syntax::ast::Program;

pub struct Compiled {
    /// As written.
    pub program: Program,
    /// After the passes.
    pub lowered: Program,
    pub env: NodeEnv,
    pub diagnostics: Vec<Diagnostic>,
    pub semantic_hash: String,
    pub full_hash: String,
}

impl Compiled {
    pub fn warnings(&self) -> impl Iterator<Item = &Diagnostic> {
        self.diagnostics.iter().filter(|d| !d.is_error())
    }
}

/// The node environment, with a signature failure reported as diagnostic `E002`.
pub fn env_for(
    program: &Program,
    libraries: &[Arc<Library>],
    base_dir: Option<&Path>,
    sig_path: &[PathBuf],
) -> Result<NodeEnv> {
    build_env(program, libraries, base_dir, sig_path, false).map_err(|e| match e {
        KirError::Signature(m) => KirError::Check(vec![Diagnostic::new("E002", m, None)]),
        other => other,
    })
}

/// Check, then run the passes (default: all); fail with `KirError::Check` on errors.
pub fn compile_program(
    program: Program,
    libraries: &[Arc<Library>],
    base_dir: Option<&Path>,
    sig_path: &[PathBuf],
    passes: Option<&[&str]>,
) -> Result<Compiled> {
    let mut env = env_for(&program, libraries, base_dir, sig_path)?;
    let diagnostics = check(&program, &env);
    if diagnostics.iter().any(Diagnostic::is_error) {
        return Err(KirError::Check(diagnostics));
    }
    let lowered = run_passes(&program, &env, passes)?;
    env.internal = true;
    let (semantic_hash, full_hash) = (semantic_hash(&lowered)?, full_hash(&lowered)?);
    Ok(Compiled { program, lowered, env, diagnostics, semantic_hash, full_hash })
}
