//! One call from a parsed program to a checked program, its optimized form and hashes.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::check::{check, Diagnostic};
use crate::errors::{KirError, Result};
use crate::lower::{full_hash, run_passes, semantic_hash};
use crate::modules::{link_program, sha256, ModuleMap};
use crate::sig::env::{build_env, qualify_record_types, NodeEnv};
use crate::sig::model::Library;
use crate::syntax::ast::Program;
use crate::util::json::Json;

pub struct Compiled {
    /// Linked program, before transformation passes.
    pub program: Program,
    /// Authored declarations, before linking.
    pub source_program: Program,
    pub dependencies: Json,
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
    compile_program_with_modules(program, libraries, base_dir, sig_path, passes, None, "<text>")
}

/// Compile with portable source resources. A supplied module map never falls
/// back to source files; signatures still use their existing resolver.
pub fn compile_program_with_modules(
    source_program: Program,
    libraries: &[Arc<Library>],
    base_dir: Option<&Path>,
    sig_path: &[PathBuf],
    passes: Option<&[&str]>,
    modules: Option<&ModuleMap>,
    source_name: &str,
) -> Result<Compiled> {
    let linked =
        link_program(&source_program, libraries, base_dir, sig_path, modules, source_name).map_err(|e| match e {
            KirError::Signature(m) => KirError::Check(vec![Diagnostic::new("E002", m, None)]),
            other => other,
        })?;
    let mut program = linked.program;
    let mut env = env_for(&program, &linked.libraries, base_dir, sig_path)?;
    if env.libraries.iter().any(|(lib, _)| !lib.records.is_empty()) {
        program = qualify_record_types(&program, &env)
            .map_err(|e| KirError::Check(vec![Diagnostic::new("E002", e.to_string(), None)]))?;
        env = env_for(&program, &linked.libraries, base_dir, sig_path)?;
    }
    let diagnostics = check(&program, &env);
    if diagnostics.iter().any(Diagnostic::is_error) {
        return Err(KirError::Check(diagnostics));
    }
    let lowered = run_passes(&program, &env, passes)?;
    env.internal = true;
    let (mut semantic_hash, mut full_hash) = (semantic_hash(&lowered)?, full_hash(&lowered)?);
    if let Some(hash) = linked.dependencies.get("hash").and_then(Json::as_str) {
        semantic_hash = sha256(&format!("{semantic_hash}\u{1f}{hash}"));
        full_hash = sha256(&format!("{full_hash}\u{1f}{hash}"));
    }
    Ok(Compiled {
        program,
        source_program,
        dependencies: linked.dependencies,
        lowered,
        env,
        diagnostics,
        semantic_hash,
        full_hash,
    })
}
