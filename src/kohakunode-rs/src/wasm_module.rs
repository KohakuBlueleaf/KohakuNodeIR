//! wasm-bindgen exports mirroring the PyO3 API.
//!
//! Every function takes JSON `&str` input and returns JSON `String` output
//! (or `Result<_, JsValue>` on error), matching the same internal Rust
//! functions that the PyO3 wrappers call.

use wasm_bindgen::prelude::*;

use crate::ast::Program;
use crate::kirgraph::KirGraph;

// ---------------------------------------------------------------------------
// Panic hook
// ---------------------------------------------------------------------------

/// Initialise `console_error_panic_hook` for better WASM error messages.
#[wasm_bindgen(start)]
pub fn start() {
    console_error_panic_hook::set_once();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn to_js(e: impl std::fmt::Display) -> JsValue {
    JsValue::from_str(&e.to_string())
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

/// Parse KIR source text and return the AST as a JSON string.
#[wasm_bindgen]
pub fn parse_kir(text: &str) -> Result<String, JsValue> {
    let program = crate::parser::parse(text).map_err(to_js)?;
    serde_json::to_string(&program).map_err(to_js)
}

// ---------------------------------------------------------------------------
// Compiler
// ---------------------------------------------------------------------------

/// Compile dataflow ordering on a Program JSON string.
#[wasm_bindgen]
pub fn compile_dataflow(program_json: &str) -> Result<String, JsValue> {
    let program: Program = serde_json::from_str(program_json).map_err(to_js)?;
    let result = crate::compiler::dataflow::compile_dataflow(&program).map_err(to_js)?;
    serde_json::to_string(&result).map_err(to_js)
}

/// Strip all `@meta` annotations from a Program JSON string.
#[wasm_bindgen]
pub fn strip_meta(program_json: &str) -> Result<String, JsValue> {
    let program: Program = serde_json::from_str(program_json).map_err(to_js)?;
    let result = crate::compiler::strip_meta::strip_meta(&program);
    serde_json::to_string(&result).map_err(to_js)
}

// ---------------------------------------------------------------------------
// KirGraph compiler
// ---------------------------------------------------------------------------

/// Compile a KirGraph JSON string (L1) to a KIR Program JSON string (L2).
#[wasm_bindgen]
pub fn compile_kirgraph(kirgraph_json: &str) -> Result<String, JsValue> {
    let graph = KirGraph::from_json(kirgraph_json).map_err(to_js)?;
    let program = crate::kirgraph::compiler::compile(&graph);
    serde_json::to_string(&program).map_err(to_js)
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

/// Parse KIR source and extract a graph as a JSON string.
#[wasm_bindgen]
pub fn kir_to_graph(source: &str) -> Result<String, JsValue> {
    let graph = crate::layout::kir_to_graph(source).map_err(to_js)?;
    Ok(graph.to_json())
}

/// Run auto-layout on a KirGraph JSON string, return updated JSON.
#[wasm_bindgen]
pub fn auto_layout(graph_json: &str) -> Result<String, JsValue> {
    let graph = KirGraph::from_json(graph_json).map_err(to_js)?;
    let laid_out = crate::layout::auto_layout::auto_layout(&graph);
    Ok(laid_out.to_json())
}

/// Score a KirGraph layout, return the total score.
#[wasm_bindgen]
pub fn score_layout(graph_json: &str) -> Result<f64, JsValue> {
    let graph = KirGraph::from_json(graph_json).map_err(to_js)?;
    let score = crate::layout::score::score_layout(&graph);
    Ok(score.total)
}

/// Run layout optimizer on a KirGraph JSON string, return updated JSON.
#[wasm_bindgen]
pub fn optimize_layout(graph_json: &str, max_iterations: usize) -> Result<String, JsValue> {
    let graph = KirGraph::from_json(graph_json).map_err(to_js)?;
    let optimized = crate::layout::optimizer::optimize_layout(&graph, max_iterations);
    Ok(optimized.to_json())
}

// ---------------------------------------------------------------------------
// Serializer
// ---------------------------------------------------------------------------

/// Serialize a Program JSON string back to KIR source text.
#[wasm_bindgen]
pub fn write_kir(program_json: &str) -> Result<String, JsValue> {
    let program: Program = serde_json::from_str(program_json).map_err(to_js)?;
    Ok(crate::serializer::write(&program))
}

// ---------------------------------------------------------------------------
// Decompiler
// ---------------------------------------------------------------------------

/// Decompile a Program JSON string (L2) back to a KirGraph JSON string (L1).
#[wasm_bindgen]
pub fn decompile(program_json: &str) -> Result<String, JsValue> {
    let program: Program = serde_json::from_str(program_json).map_err(to_js)?;
    let graph = crate::kirgraph::decompile(&program);
    Ok(graph.to_json())
}
