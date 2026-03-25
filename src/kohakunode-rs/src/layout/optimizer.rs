//! Layout optimizer for KirGraph — local-search placement improvement.
//!
//! Port of `kohakunode/layout/optimizer.py`.
//!
//! Starts from the auto-layout result and iteratively improves it by
//! trying swaps, column moves, and row shifts that reduce the total
//! layout score (wire-bending cost).

use std::collections::HashMap;

use crate::ast::Value;
use crate::kirgraph::{KGEdge, KGNode, KirGraph};
use crate::layout::auto_layout::{
    auto_layout, estimate_node_size, H_SPACING, MIN_HEIGHT, MIN_WIDTH, V_SPACING,
};
use crate::layout::score::{
    count_crossings, count_overlaps, score_edge, CROSSING_PENALTY, OVERLAP_PENALTY,
};

// ---------------------------------------------------------------------------
// Grid helpers
// ---------------------------------------------------------------------------

fn grid_from_graph(graph: &KirGraph) -> (HashMap<String, (i32, i32)>, HashMap<String, (f64, f64)>) {
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

fn total_score(
    grid: &HashMap<String, (i32, i32)>,
    _sizes: &HashMap<String, (f64, f64)>,
    edges: &[KGEdge],
) -> f64 {
    let edge_cost: f64 = edges.iter().map(|e| score_edge(e, grid)).sum();
    let crossing_cost = count_crossings(grid, edges) as f64 * CROSSING_PENALTY;
    let overlap_cost = count_overlaps(grid) as f64 * OVERLAP_PENALTY;
    edge_cost + crossing_cost + overlap_cost
}

fn apply_grid_to_graph(
    graph: &KirGraph,
    grid: &HashMap<String, (i32, i32)>,
    sizes: &HashMap<String, (f64, f64)>,
) -> KirGraph {
    let mut cols_used: HashMap<i32, Vec<String>> = HashMap::new();
    let mut rows_used: HashMap<i32, Vec<String>> = HashMap::new();
    for (nid, (c, r)) in grid {
        cols_used.entry(*c).or_default().push(nid.clone());
        rows_used.entry(*r).or_default().push(nid.clone());
    }

    // Column x-offsets based on max width in each column
    let mut sorted_cols: Vec<i32> = cols_used.keys().cloned().collect();
    sorted_cols.sort();
    let mut col_x: HashMap<i32, f64> = HashMap::new();
    let mut x = 100.0f64;
    for c in &sorted_cols {
        col_x.insert(*c, x);
        let max_w = cols_used[c]
            .iter()
            .filter_map(|nid| sizes.get(nid).map(|(w, _)| *w))
            .fold(MIN_WIDTH, f64::max);
        x += max_w + H_SPACING;
    }

    // Row y-offsets based on max height in each row
    let mut sorted_rows: Vec<i32> = rows_used.keys().cloned().collect();
    sorted_rows.sort();
    let mut row_y: HashMap<i32, f64> = HashMap::new();
    let mut y = 100.0f64;
    for r in &sorted_rows {
        row_y.insert(*r, y);
        let max_h = rows_used[r]
            .iter()
            .filter_map(|nid| sizes.get(nid).map(|(_, h)| *h))
            .fold(MIN_HEIGHT, f64::max);
        y += max_h + V_SPACING;
    }

    let mut new_nodes: Vec<KGNode> = Vec::new();
    for node in &graph.nodes {
        let (c, r) = grid[&node.id];
        let mut new_meta = node.meta.clone();
        new_meta.insert(
            "pos".to_string(),
            Value::List(vec![
                Value::Int(*col_x.get(&c).unwrap_or(&100.0) as i64),
                Value::Int(*row_y.get(&r).unwrap_or(&100.0) as i64),
            ]),
        );
        let (w, h) = sizes
            .get(&node.id)
            .copied()
            .unwrap_or((MIN_WIDTH, MIN_HEIGHT));
        new_meta.insert(
            "size".to_string(),
            Value::List(vec![Value::Int(w as i64), Value::Int(h as i64)]),
        );
        new_nodes.push(KGNode {
            id: node.id.clone(),
            r#type: node.r#type.clone(),
            name: node.name.clone(),
            data_inputs: node.data_inputs.clone(),
            data_outputs: node.data_outputs.clone(),
            ctrl_inputs: node.ctrl_inputs.clone(),
            ctrl_outputs: node.ctrl_outputs.clone(),
            properties: node.properties.clone(),
            meta: new_meta,
        });
    }

    KirGraph {
        version: graph.version.clone(),
        nodes: new_nodes,
        edges: graph.edges.clone(),
    }
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Improve layout by swapping/moving nodes to minimize score.
///
/// 1. Start from `auto_layout` result.
/// 2. Build grid assignments (col, row for each node).
/// 3. On each iteration, try local moves and accept improvements.
/// 4. Stop when no improvement found or `max_iterations` exhausted.
///
/// Returns a new [`KirGraph`] with optimized positions.
pub fn optimize_layout(graph: &KirGraph, max_iterations: usize) -> KirGraph {
    let graph = auto_layout(graph);
    let (mut grid, sizes) = grid_from_graph(&graph);
    let edges = graph.edges.clone();
    let node_ids: Vec<String> = grid.keys().cloned().collect();

    if node_ids.len() <= 1 || edges.is_empty() {
        return graph;
    }

    let mut best_score = total_score(&grid, &sizes, &edges);

    for _iteration in 0..max_iterations {
        let mut improved = false;

        // --- Strategy A: swap two nodes within the same column ---
        let mut cols: HashMap<i32, Vec<String>> = HashMap::new();
        for (nid, (c, _r)) in &grid {
            cols.entry(*c).or_default().push(nid.clone());
        }

        for col_nodes in cols.values() {
            if col_nodes.len() < 2 {
                continue;
            }
            let nodes: Vec<String> = col_nodes.clone();
            for i in 0..nodes.len() {
                for j in i + 1..nodes.len() {
                    let a = &nodes[i];
                    let b = &nodes[j];
                    let a_row = grid[a].1;
                    let b_row = grid[b].1;
                    // Swap rows
                    grid.get_mut(a).unwrap().1 = b_row;
                    grid.get_mut(b).unwrap().1 = a_row;
                    let new_score = total_score(&grid, &sizes, &edges);
                    if new_score < best_score {
                        best_score = new_score;
                        improved = true;
                    } else {
                        // Revert
                        grid.get_mut(a).unwrap().1 = a_row;
                        grid.get_mut(b).unwrap().1 = b_row;
                    }
                }
            }
        }

        // --- Strategy B: move a node to an adjacent column ---
        for nid in &node_ids {
            let (old_col, _old_row) = grid[nid];
            for delta_c in &[-1i32, 1i32] {
                let new_col = old_col + delta_c;
                if new_col < 0 {
                    continue;
                }
                grid.get_mut(nid).unwrap().0 = new_col;
                let new_score = total_score(&grid, &sizes, &edges);
                if new_score < best_score {
                    best_score = new_score;
                    improved = true;
                } else {
                    grid.get_mut(nid).unwrap().0 = old_col;
                }
            }
        }

        // --- Strategy C: move a node to an adjacent row ---
        for nid in &node_ids {
            let (_old_col, old_row) = grid[nid];
            for delta_r in &[-1i32, 1i32] {
                let new_row = old_row + delta_r;
                if new_row < 0 {
                    continue;
                }
                grid.get_mut(nid).unwrap().1 = new_row;
                let new_score = total_score(&grid, &sizes, &edges);
                if new_score < best_score {
                    best_score = new_score;
                    improved = true;
                } else {
                    grid.get_mut(nid).unwrap().1 = old_row;
                }
            }
        }

        if !improved {
            break;
        }
    }

    apply_grid_to_graph(&graph, &grid, &sizes)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::layout::kir_to_graph;
    use crate::layout::score::score_layout;

    #[test]
    fn test_optimize_layout_runs() {
        let source = r#"
x = 1
y = 2
(x, y)add(z)
(z)print()
"#;
        let graph = kir_to_graph(source).expect("parse failed");
        let optimized = optimize_layout(&graph, 10);
        assert_eq!(optimized.nodes.len(), graph.nodes.len());
    }

    #[test]
    fn test_optimize_layout_all_nodes_positioned() {
        let source = r#"
a = 1
(a)print()
"#;
        let graph = kir_to_graph(source).expect("parse failed");
        let optimized = optimize_layout(&graph, 20);
        for node in &optimized.nodes {
            assert!(
                node.meta.contains_key("pos"),
                "node {} missing pos after optimize_layout",
                node.id
            );
        }
    }

    #[test]
    fn test_optimize_does_not_increase_score() {
        let source = r#"
x = 10
y = 20
(x, y)add(z)
(z)print()
"#;
        let graph = kir_to_graph(source).expect("parse failed");
        let initial_laid = crate::layout::auto_layout::auto_layout(&graph);
        let initial_score = score_layout(&initial_laid).total;
        let optimized = optimize_layout(&graph, 50);
        let optimized_score = score_layout(&optimized).total;
        assert!(
            optimized_score <= initial_score + 0.001,
            "optimize_layout increased score: before={} after={}",
            initial_score,
            optimized_score
        );
    }
}
