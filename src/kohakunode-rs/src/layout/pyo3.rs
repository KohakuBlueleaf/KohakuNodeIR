//! PyO3 bindings for the layout module.
//!
//! Exposes `kir_to_graph`, `auto_layout`, `score_layout`, and
//! `optimize_layout` to Python.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::kirgraph::KirGraph;
use crate::layout::{
    auto_layout::auto_layout, kir_to_graph, optimizer::optimize_layout, score::score_layout,
};

/// Parse KIR source and extract a graph as a JSON string.
#[pyfunction]
pub fn py_kir_to_graph(source: &str) -> PyResult<String> {
    let graph = kir_to_graph(source)
        .map_err(|e| PyValueError::new_err(format!("kir_to_graph error: {}", e)))?;
    Ok(graph.to_json())
}

/// Run auto-layout on a KirGraph JSON string, return updated JSON.
#[pyfunction]
pub fn py_auto_layout(graph_json: &str) -> PyResult<String> {
    let graph = KirGraph::from_json(graph_json)
        .map_err(|e| PyValueError::new_err(format!("invalid graph JSON: {}", e)))?;
    let laid_out = auto_layout(&graph);
    Ok(laid_out.to_json())
}

/// Score a KirGraph JSON string, return the total score as a float.
#[pyfunction]
pub fn py_score_layout(graph_json: &str) -> PyResult<f64> {
    let graph = KirGraph::from_json(graph_json)
        .map_err(|e| PyValueError::new_err(format!("invalid graph JSON: {}", e)))?;
    let score = score_layout(&graph);
    Ok(score.total)
}

/// Run optimizer on a KirGraph JSON string, return updated JSON.
#[pyfunction]
#[pyo3(signature = (graph_json, max_iterations=100))]
pub fn py_optimize_layout(graph_json: &str, max_iterations: usize) -> PyResult<String> {
    let graph = KirGraph::from_json(graph_json)
        .map_err(|e| PyValueError::new_err(format!("invalid graph JSON: {}", e)))?;
    let optimized = optimize_layout(&graph, max_iterations);
    Ok(optimized.to_json())
}

/// Register layout functions into a Python module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_kir_to_graph, m)?)?;
    m.add_function(wrap_pyfunction!(py_auto_layout, m)?)?;
    m.add_function(wrap_pyfunction!(py_score_layout, m)?)?;
    m.add_function(wrap_pyfunction!(py_optimize_layout, m)?)?;
    Ok(())
}
