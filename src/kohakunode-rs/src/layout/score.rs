//! Layout quality scoring for KirGraph — measures wire bending cost.
//!
//! Port of `kohakunode/layout/score.py`.
//!
//! Each node is mapped to a (col, row) grid cell derived from its pixel
//! position and estimated size.  Edges are scored by deviation from their
//! ideal direction:
//!
//! * **Control edges** should flow top-to-bottom within the same column.
//! * **Data edges** should flow left-to-right within the same row.
//!
//! Additional penalties:
//! * **Edge crossings**: approximate crossing count between adjacent columns.
//! * **Node overlap**: penalty for nodes sharing the same grid cell.
//!
//! Total score = sum of all edge costs + crossing penalty + overlap penalty.
//! Lower is better; 0 is perfect.

use std::collections::HashMap;

use crate::ast::Value;
use crate::kirgraph::{KGEdge, KirGraph};
use crate::layout::auto_layout::estimate_node_size;

// ---------------------------------------------------------------------------
// Tuning constants
// ---------------------------------------------------------------------------

pub const CROSSING_PENALTY: f64 = 2.0;
pub const OVERLAP_PENALTY: f64 = 10.0;

// ---------------------------------------------------------------------------
// Score types
// ---------------------------------------------------------------------------

/// Detailed score for a single edge.
#[derive(Debug, Clone)]
pub struct EdgeScore {
    pub edge: KGEdge,
    pub cost: f64,
    pub col_diff: i32,
    pub row_diff: i32,
}

/// Aggregate layout quality report.
#[derive(Debug, Clone)]
pub struct LayoutScore {
    pub total: f64,
    pub max_edge_cost: f64,
    pub avg_edge_cost: f64,
    pub edge_scores: Vec<EdgeScore>,
    pub crossing_penalty: f64,
    pub overlap_penalty: f64,
}

// ---------------------------------------------------------------------------
// Grid building
// ---------------------------------------------------------------------------

/// Map each node to (col, row) grid coordinates.
pub fn build_grid(graph: &KirGraph) -> (HashMap<String, (i32, i32)>, HashMap<String, (f64, f64)>) {
    let mut positions: HashMap<String, (f64, f64)> = HashMap::new();
    let mut sizes: HashMap<String, (f64, f64)> = HashMap::new();

    for node in &graph.nodes {
        let pos = node.meta.get("pos");
        let (px, py) = match pos {
            Some(Value::List(v)) if v.len() >= 2 => {
                let x = match &v[0] {
                    Value::Int(i) => *i as f64,
                    Value::Float(f) => *f,
                    _ => 0.0,
                };
                let y = match &v[1] {
                    Value::Int(i) => *i as f64,
                    Value::Float(f) => *f,
                    _ => 0.0,
                };
                (x, y)
            }
            _ => (0.0, 0.0),
        };
        positions.insert(node.id.clone(), (px, py));

        let (mut w, mut h) = estimate_node_size(node);
        if let Some(Value::List(s)) = node.meta.get("size") {
            if s.len() >= 2 {
                let sw = match &s[0] {
                    Value::Int(i) => *i as f64,
                    Value::Float(f) => *f,
                    _ => 0.0,
                };
                let sh = match &s[1] {
                    Value::Int(i) => *i as f64,
                    Value::Float(f) => *f,
                    _ => 0.0,
                };
                if sw > w {
                    w = sw;
                }
                if sh > h {
                    h = sh;
                }
            }
        }
        sizes.insert(node.id.clone(), (w, h));
    }

    // Build column and row indices from sorted unique coordinates
    let mut xs: Vec<f64> = positions.values().map(|(x, _)| *x).collect();
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    xs.dedup_by(|a, b| (*a - *b).abs() < f64::EPSILON);

    let mut ys: Vec<f64> = positions.values().map(|(_, y)| *y).collect();
    ys.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    ys.dedup_by(|a, b| (*a - *b).abs() < f64::EPSILON);

    let x_to_col: HashMap<i64, i32> = xs
        .iter()
        .enumerate()
        .map(|(i, x)| (*x as i64, i as i32))
        .collect();
    let y_to_row: HashMap<i64, i32> = ys
        .iter()
        .enumerate()
        .map(|(i, y)| (*y as i64, i as i32))
        .collect();

    let mut grid: HashMap<String, (i32, i32)> = HashMap::new();
    for (nid, (px, py)) in &positions {
        let col = x_to_col.get(&(*px as i64)).copied().unwrap_or(0);
        let row = y_to_row.get(&(*py as i64)).copied().unwrap_or(0);
        grid.insert(nid.clone(), (col, row));
    }

    (grid, sizes)
}

// ---------------------------------------------------------------------------
// Edge scoring
// ---------------------------------------------------------------------------

/// Score a single edge by its deviation from the ideal direction.
/// Returns cost; 0 = ideal placement.
pub fn score_edge(edge: &KGEdge, grid: &HashMap<String, (i32, i32)>) -> f64 {
    let src = match grid.get(&edge.from_node) {
        Some(p) => *p,
        None => return 0.0,
    };
    let dst = match grid.get(&edge.to_node) {
        Some(p) => *p,
        None => return 0.0,
    };

    let col_diff = dst.0 - src.0;
    let row_diff = dst.1 - src.1;

    if edge.r#type == "control" {
        if row_diff < 0 {
            // Backward ctrl edge (loop back): 3x penalty on both axes
            (row_diff.abs() as f64) * 3.0 + (col_diff.abs() as f64) * 3.0
        } else if row_diff == 0 {
            // Same row ctrl = bad
            2.0 + (col_diff.abs() as f64) * 3.0
        } else {
            // Forward ctrl: col deviation strongly penalised, row_diff=1 free
            let col_penalty = (col_diff.abs() as f64) * 3.0;
            let row_penalty = (row_diff - 1).max(0) as f64;
            col_penalty + row_penalty
        }
    } else {
        // Data edge
        if col_diff < 0 {
            // Backward data edge: 3x penalty
            (col_diff.abs() as f64) * 3.0 + (row_diff.abs() as f64) * 2.0
        } else if col_diff == 0 {
            // Same column data = mildly bad
            1.0 + (row_diff.abs() as f64) * 2.0
        } else {
            // Forward data: row deviation strongly penalised, col_diff=1 free
            let col_penalty = (col_diff - 1).max(0) as f64;
            let row_penalty = (row_diff.abs() as f64) * 2.0;
            col_penalty + row_penalty
        }
    }
}

// ---------------------------------------------------------------------------
// Crossing count
// ---------------------------------------------------------------------------

pub fn count_crossings(grid: &HashMap<String, (i32, i32)>, edges: &[KGEdge]) -> i32 {
    let mut col_pair_edges: HashMap<(i32, i32), Vec<(f64, f64)>> = HashMap::new();

    for edge in edges {
        let src = match grid.get(&edge.from_node) {
            Some(p) => *p,
            None => continue,
        };
        let dst = match grid.get(&edge.to_node) {
            Some(p) => *p,
            None => continue,
        };

        let (mut src_col, mut src_row, mut dst_col, mut dst_row) = (src.0, src.1, dst.0, dst.1);

        if src_col == dst_col {
            continue; // vertical edges don't cross horizontally
        }

        // Normalise direction: always left-to-right
        if src_col > dst_col {
            std::mem::swap(&mut src_col, &mut dst_col);
            std::mem::swap(&mut src_row, &mut dst_row);
        }

        let span = dst_col - src_col;
        for step in 0..span {
            let left_col = src_col + step;
            let right_col = left_col + 1;
            let t_left = step as f64 / span as f64;
            let t_right = (step + 1) as f64 / span as f64;
            let row_left = src_row as f64 + t_left * (dst_row - src_row) as f64;
            let row_right = src_row as f64 + t_right * (dst_row - src_row) as f64;
            col_pair_edges
                .entry((left_col, right_col))
                .or_default()
                .push((row_left, row_right));
        }
    }

    let mut total_crossings = 0i32;
    for pair_edges in col_pair_edges.values() {
        let n = pair_edges.len();
        if n < 2 {
            continue;
        }
        for i in 0..n {
            for j in i + 1..n {
                let (a_left, a_right) = pair_edges[i];
                let (b_left, b_right) = pair_edges[j];
                if (a_left < b_left && a_right > b_right) || (a_left > b_left && a_right < b_right)
                {
                    total_crossings += 1;
                }
            }
        }
    }
    total_crossings
}

// ---------------------------------------------------------------------------
// Overlap count
// ---------------------------------------------------------------------------

pub fn count_overlaps(grid: &HashMap<String, (i32, i32)>) -> i32 {
    let mut cell_counts: HashMap<(i32, i32), i32> = HashMap::new();
    for pos in grid.values() {
        *cell_counts.entry(*pos).or_insert(0) += 1;
    }
    let mut overlaps = 0i32;
    for count in cell_counts.values() {
        if *count > 1 {
            overlaps += count * (count - 1) / 2;
        }
    }
    overlaps
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Calculate layout quality score. Lower = better.
pub fn score_layout(graph: &KirGraph) -> LayoutScore {
    if graph.edges.is_empty() {
        return LayoutScore {
            total: 0.0,
            max_edge_cost: 0.0,
            avg_edge_cost: 0.0,
            edge_scores: vec![],
            crossing_penalty: 0.0,
            overlap_penalty: 0.0,
        };
    }

    let (grid, _sizes) = build_grid(graph);

    let mut edge_scores: Vec<EdgeScore> = Vec::new();
    for edge in &graph.edges {
        let cost = score_edge(edge, &grid);
        let src = grid.get(&edge.from_node).copied().unwrap_or((0, 0));
        let dst = grid.get(&edge.to_node).copied().unwrap_or((0, 0));
        edge_scores.push(EdgeScore {
            edge: edge.clone(),
            cost,
            col_diff: dst.0 - src.0,
            row_diff: dst.1 - src.1,
        });
    }

    let edge_total: f64 = edge_scores.iter().map(|es| es.cost).sum();
    let max_cost = edge_scores
        .iter()
        .map(|es| es.cost)
        .fold(f64::NEG_INFINITY, f64::max);
    let avg_cost = if edge_scores.is_empty() {
        0.0
    } else {
        edge_total / edge_scores.len() as f64
    };

    let crossings = count_crossings(&grid, &graph.edges);
    let crossing_cost = crossings as f64 * CROSSING_PENALTY;

    let overlaps = count_overlaps(&grid);
    let overlap_cost = overlaps as f64 * OVERLAP_PENALTY;

    let total = edge_total + crossing_cost + overlap_cost;

    LayoutScore {
        total,
        max_edge_cost: max_cost,
        avg_edge_cost: avg_cost,
        edge_scores,
        crossing_penalty: crossing_cost,
        overlap_penalty: overlap_cost,
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::layout::{auto_layout::auto_layout, kir_to_graph};

    #[test]
    fn test_score_layout_computes() {
        let source = r#"
x = 1
y = 2
(x, y)add(z)
(z)print()
"#;
        let graph = kir_to_graph(source).expect("parse failed");
        let laid_out = auto_layout(&graph);
        let score = score_layout(&laid_out);
        assert!(
            score.total >= 0.0,
            "score must be non-negative, got {}",
            score.total
        );
        assert!(
            score.avg_edge_cost >= 0.0,
            "avg_edge_cost must be non-negative"
        );
    }

    #[test]
    fn test_score_empty_graph() {
        let graph = KirGraph::default();
        let score = score_layout(&graph);
        assert_eq!(score.total, 0.0);
        assert_eq!(score.max_edge_cost, 0.0);
        assert_eq!(score.avg_edge_cost, 0.0);
    }

    #[test]
    fn test_score_mixed_mode() {
        let source = include_str!("../../../../examples/kir_basics/mixed_mode.kir");
        let graph = kir_to_graph(source).expect("parse failed");
        let laid_out = auto_layout(&graph);
        let score = score_layout(&laid_out);
        assert!(score.total >= 0.0);
        assert!(!score.edge_scores.is_empty());
    }

    #[test]
    fn test_score_edge_control_forward() {
        // A forward ctrl edge in the same column with row_diff=1 should have 0 cost
        let mut grid = HashMap::new();
        grid.insert("a".to_string(), (0, 0));
        grid.insert("b".to_string(), (0, 1));
        let edge = KGEdge::control("a", "out", "b", "in");
        let cost = score_edge(&edge, &grid);
        assert_eq!(cost, 0.0, "perfect forward ctrl edge should cost 0");
    }

    #[test]
    fn test_score_edge_data_forward() {
        // A forward data edge in the same row with col_diff=1 should have 0 cost
        let mut grid = HashMap::new();
        grid.insert("a".to_string(), (0, 0));
        grid.insert("b".to_string(), (1, 0));
        let edge = KGEdge::data("a", "out", "b", "in");
        let cost = score_edge(&edge, &grid);
        assert_eq!(cost, 0.0, "perfect forward data edge should cost 0");
    }

    #[test]
    fn test_score_edge_ctrl_backward_has_penalty() {
        let mut grid = HashMap::new();
        grid.insert("a".to_string(), (0, 5));
        grid.insert("b".to_string(), (0, 0));
        let edge = KGEdge::control("a", "out", "b", "in");
        let cost = score_edge(&edge, &grid);
        assert!(cost > 0.0, "backward ctrl edge must have positive cost");
    }
}
