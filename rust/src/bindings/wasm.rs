//! wasm-bindgen exports for the browser editor; errors become JS `Error`s.

use wasm_bindgen::prelude::*;

use crate::api;
use crate::errors::KirError;

fn js_err(e: KirError) -> JsError {
    JsError::new(&format!("{}: {e}", e.kind()))
}

#[wasm_bindgen(js_name = parseToJson)]
pub fn parse_to_json(source: &str) -> Result<String, JsError> {
    api::parse_to_json(source).map_err(js_err)
}

#[wasm_bindgen(js_name = format)]
pub fn format_source(source: &str) -> Result<String, JsError> {
    api::format(source).map_err(js_err)
}

#[wasm_bindgen]
pub fn check(source: &str, sigs: Vec<String>) -> Result<String, JsError> {
    api::check(source, api::Signatures::texts(&sigs)).map_err(js_err)
}

/// `passes` undefined runs every pass.
#[wasm_bindgen]
pub fn lower(source: &str, sigs: Vec<String>, passes: Option<Vec<String>>) -> Result<String, JsError> {
    api::lower(source, api::Signatures::texts(&sigs), passes.as_deref()).map_err(js_err)
}

#[wasm_bindgen]
pub fn hashes(source: &str, sigs: Vec<String>, passes: Option<Vec<String>>) -> Result<String, JsError> {
    api::hashes(source, api::Signatures::texts(&sigs), passes.as_deref()).map_err(js_err)
}

/// `data` undefined is `"wires"`; `"variables"` draws reads and writes as variable nodes.
#[wasm_bindgen(js_name = toGraph)]
pub fn to_graph(source: &str, sigs: Vec<String>, data: Option<String>) -> Result<String, JsError> {
    api::to_graph(source, api::Signatures::texts(&sigs), data.as_deref().unwrap_or("wires")).map_err(js_err)
}

#[wasm_bindgen(js_name = fromGraph)]
pub fn from_graph(graph: &str, with_meta: bool) -> Result<String, JsError> {
    api::from_graph(graph, with_meta).map_err(js_err)
}

/// Source resources are a JSON object of portable module IDs to source strings.
#[wasm_bindgen(js_name = linkModules)]
pub fn link_modules(source: &str, modules: &str, source_name: &str, sigs: Vec<String>) -> Result<String, JsError> {
    api::link_modules(source, modules, source_name, api::Signatures::texts(&sigs)).map_err(js_err)
}

#[wasm_bindgen(js_name = compileModules)]
pub fn compile_modules(
    source: &str,
    modules: &str,
    source_name: &str,
    sigs: Vec<String>,
    passes: Option<Vec<String>>,
) -> Result<String, JsError> {
    api::compile_modules(source, modules, source_name, api::Signatures::texts(&sigs), passes.as_deref()).map_err(js_err)
}

#[wasm_bindgen(js_name = stdSignatures)]
pub fn std_signatures() -> Result<String, JsError> {
    api::std_signatures().map_err(js_err)
}
