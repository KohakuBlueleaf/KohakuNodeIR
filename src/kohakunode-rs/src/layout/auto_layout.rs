//! Auto-layout for KirGraph nodes — Fischer-style.
//!
//! Port of `kohakunode/layout/auto_layout.py`.
//!
//! Strategy:
//! 1. Find control flow root, place at grid (0, 0)
//! 2. Layout control chain downward (col 0, increasing rows)
//! 3. For each ctrl node, place data sources to the LEFT
//! 4. Place data consumers to the RIGHT
//! 5. Grid uses negative indices freely — shift to positive at the end

use std::collections::{HashMap, HashSet, VecDeque};

use crate::ast::Value;
use crate::kirgraph::{KGNode, KirGraph};

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------

pub const CTRL_ROW_H: f64 = 18.0;
pub const HEADER_H: f64 = 32.0;
pub const DATA_ROW_H: f64 = 28.0;
pub const MIN_WIDTH: f64 = 180.0;
pub const MIN_HEIGHT: f64 = 100.0;
pub const H_SPACING: f64 = 60.0;
pub const V_SPACING: f64 = 60.0;

const FOLD_TYPES: &[&str] = &["branch", "merge", "switch", "parallel"];

// ---------------------------------------------------------------------------
// Node size estimation
// ---------------------------------------------------------------------------

pub fn estimate_node_size(node: &KGNode) -> (f64, f64) {
    let n_data = node.data_inputs.len().max(node.data_outputs.len()) as f64;
    let n_ci = node.ctrl_inputs.len() as f64;
    let n_co = node.ctrl_outputs.len() as f64;
    let w = MIN_WIDTH.max(n_ci.max(n_co) * 60.0 + 60.0);
    let h = if node.r#type == "merge" {
        (if n_ci > 0.0 { CTRL_ROW_H } else { 0.0 })
            + HEADER_H
            + (if n_co > 0.0 { CTRL_ROW_H } else { 0.0 })
            + 8.0
    } else {
        MIN_HEIGHT.max(
            (if n_ci > 0.0 { CTRL_ROW_H } else { 0.0 })
                + HEADER_H
                + n_data * DATA_ROW_H
                + (if n_co > 0.0 { CTRL_ROW_H } else { 0.0 })
                + 8.0,
        )
    };
    (w, h)
}

// ---------------------------------------------------------------------------
// Adjacency helpers
// ---------------------------------------------------------------------------

fn build_adjacency(
    graph: &KirGraph,
) -> (
    HashMap<String, Vec<String>>,
    HashMap<String, Vec<String>>,
    HashMap<String, Vec<String>>,
    HashMap<String, Vec<String>>,
) {
    let mut data_adj: HashMap<String, Vec<String>> = HashMap::new();
    let mut data_rev: HashMap<String, Vec<String>> = HashMap::new();
    let mut ctrl_adj: HashMap<String, Vec<String>> = HashMap::new();
    let mut ctrl_rev: HashMap<String, Vec<String>> = HashMap::new();

    for edge in &graph.edges {
        let f = edge.from_node.clone();
        let t = edge.to_node.clone();
        if edge.r#type == "data" {
            data_adj.entry(f.clone()).or_default().push(t.clone());
            data_rev.entry(t).or_default().push(f);
        } else {
            ctrl_adj.entry(f.clone()).or_default().push(t.clone());
            ctrl_rev.entry(t).or_default().push(f);
        }
    }
    (data_adj, data_rev, ctrl_adj, ctrl_rev)
}

// ---------------------------------------------------------------------------
// Node rank computation
// ---------------------------------------------------------------------------

fn compute_node_ranks(
    node_order: &[String],
    node_map: &HashMap<String, &KGNode>,
    ctrl_adj: &HashMap<String, Vec<String>>,
) -> HashMap<String, f64> {
    let mut node_rank: HashMap<String, f64> = node_order
        .iter()
        .enumerate()
        .map(|(i, nid)| (nid.clone(), i as f64))
        .collect();

    for nid in node_order {
        if node_map.get(nid).map(|n| n.r#type.as_str()) == Some("merge") {
            if let Some(children) = ctrl_adj.get(nid) {
                for child in children {
                    if let Some(&child_rank) = node_rank.get(child) {
                        node_rank.insert(nid.clone(), child_rank - 0.5);
                        break;
                    }
                }
            }
        }
    }
    node_rank
}

// ---------------------------------------------------------------------------
// Find ctrl roots
// ---------------------------------------------------------------------------

fn find_ctrl_roots(
    node_order: &[String],
    needs_ids: &HashSet<String>,
    ctrl_nodes: &HashSet<String>,
    ctrl_adj: &HashMap<String, Vec<String>>,
    ctrl_rev: &HashMap<String, Vec<String>>,
    node_rank: &HashMap<String, f64>,
    graph: &KirGraph,
) -> Vec<String> {
    let mut ctrl_roots: Vec<String> = Vec::new();

    for nid in node_order {
        if !ctrl_nodes.contains(nid) {
            continue;
        }
        if ctrl_adj.get(nid).map(|v| v.is_empty()).unwrap_or(true) {
            continue;
        }
        let incoming: Vec<&String> = ctrl_rev
            .get(nid)
            .map(|v| v.iter().filter(|s| needs_ids.contains(*s)).collect())
            .unwrap_or_default();
        let my_rank = node_rank.get(nid).copied().unwrap_or(0.0);
        let forward_incoming: Vec<&&String> = incoming
            .iter()
            .filter(|s| node_rank.get(**s).copied().unwrap_or(999.0) < my_rank)
            .collect();
        if forward_incoming.is_empty() {
            ctrl_roots.push(nid.clone());
        }
    }

    if ctrl_roots.is_empty() && !ctrl_nodes.is_empty() {
        for nid in node_order {
            if ctrl_nodes.contains(nid) {
                return vec![nid.clone()];
            }
        }
    }

    if ctrl_roots.is_empty() {
        let all_rev: HashSet<&str> = graph.edges.iter().map(|e| e.to_node.as_str()).collect();
        ctrl_roots = needs_ids
            .iter()
            .filter(|nid| !all_rev.contains(nid.as_str()))
            .cloned()
            .collect();
    }

    if ctrl_roots.is_empty() {
        if let Some(first) = node_order.first() {
            ctrl_roots = vec![first.clone()];
        }
    }

    ctrl_roots
}

// ---------------------------------------------------------------------------
// BFS ctrl chain placement
// ---------------------------------------------------------------------------

fn bfs_ctrl_chain(
    ctrl_roots: &[String],
    ctrl_nodes: &HashSet<String>,
    needs_ids: &HashSet<String>,
    ctrl_adj: &HashMap<String, Vec<String>>,
    node_rank: &HashMap<String, f64>,
    node_order: &[String],
) -> (HashMap<String, (i32, i32)>, HashSet<String>) {
    let mut grid: HashMap<String, (i32, i32)> = HashMap::new();
    let mut placed: HashSet<String> = HashSet::new();
    let mut ctrl_row: i32 = 0;

    let mut bfs_queue: VecDeque<String> = VecDeque::new();

    let bfs_from = |start: &str,
                    grid: &mut HashMap<String, (i32, i32)>,
                    placed: &mut HashSet<String>,
                    ctrl_row: &mut i32,
                    bfs_queue: &mut VecDeque<String>| {
        if placed.contains(start) {
            return;
        }
        grid.insert(start.to_string(), (0, *ctrl_row));
        placed.insert(start.to_string());
        bfs_queue.push_back(start.to_string());
        *ctrl_row += 1;

        while let Some(nid) = bfs_queue.pop_front() {
            let my_rank = node_rank.get(&nid).copied().unwrap_or(0.0);
            if let Some(children) = ctrl_adj.get(&nid) {
                for child in children {
                    if !needs_ids.contains(child) || placed.contains(child) {
                        continue;
                    }
                    let child_rank = node_rank.get(child).copied().unwrap_or(999.0);
                    if child_rank < my_rank {
                        continue; // back edge — skip
                    }
                    grid.insert(child.clone(), (0, *ctrl_row));
                    placed.insert(child.clone());
                    bfs_queue.push_back(child.clone());
                    *ctrl_row += 1;
                }
            }
        }
    };

    if let Some(root) = ctrl_roots.first() {
        bfs_from(root, &mut grid, &mut placed, &mut ctrl_row, &mut bfs_queue);
    }

    for nid in node_order {
        if ctrl_nodes.contains(nid) && !placed.contains(nid) && needs_ids.contains(nid) {
            bfs_from(nid, &mut grid, &mut placed, &mut ctrl_row, &mut bfs_queue);
        }
    }

    (grid, placed)
}

// ---------------------------------------------------------------------------
// Grid folding
// ---------------------------------------------------------------------------

fn fold_grid(grid: &mut HashMap<String, (i32, i32)>, node_map: &HashMap<String, &KGNode>) {
    if grid.is_empty() {
        return;
    }

    let max_col = grid.values().map(|(c, _)| *c).max().unwrap_or(0);
    let min_col = grid.values().map(|(c, _)| *c).min().unwrap_or(0);
    let max_row = grid.values().map(|(_, r)| *r).max().unwrap_or(0);
    let min_row = grid.values().map(|(_, r)| *r).min().unwrap_or(0);
    let width = max_col - min_col + 1;
    let height = max_row - min_row + 1;

    if height <= 8 && width <= 12 {
        return;
    }

    if height > 8.max(width * 2) {
        fold_columns(grid, node_map, height);
    }

    // Recompute after column folding
    if !grid.is_empty() {
        let max_row2 = grid.values().map(|(_, r)| *r).max().unwrap_or(0);
        let min_row2 = grid.values().map(|(_, r)| *r).min().unwrap_or(0);
        let max_col2 = grid.values().map(|(c, _)| *c).max().unwrap_or(0);
        let min_col2 = grid.values().map(|(c, _)| *c).min().unwrap_or(0);
        let width2 = max_col2 - min_col2 + 1;
        let height2 = max_row2 - min_row2 + 1;

        if width2 > 12.max(height2 * 3) {
            fold_rows(grid, node_map, width2);
        }
    }
}

fn fold_columns(
    grid: &mut HashMap<String, (i32, i32)>,
    node_map: &HashMap<String, &KGNode>,
    _total_height: i32,
) {
    // Group nodes by column
    let mut col_nodes: HashMap<i32, Vec<(String, i32)>> = HashMap::new();
    for (nid, (c, r)) in grid.iter() {
        col_nodes.entry(*c).or_default().push((nid.clone(), *r));
    }

    let mut max_existing_col = grid.values().map(|(c, _)| *c).max().unwrap_or(0);

    let mut updates: Vec<(String, (i32, i32))> = Vec::new();

    for col in {
        let mut keys: Vec<i32> = col_nodes.keys().cloned().collect();
        keys.sort();
        keys
    } {
        let mut nodes: Vec<(String, i32)> = col_nodes[&col].clone();
        nodes.sort_by_key(|(_, r)| *r);

        if nodes.len() <= 8 {
            continue;
        }

        let mid = nodes.len() / 2;
        let mut best_split = mid as i32;

        let quarter = nodes.len() / 4;
        'outer: for offset in 0..quarter {
            for candidate in [mid as i32 + offset as i32, mid as i32 - offset as i32] {
                if candidate > 0 && candidate < nodes.len() as i32 {
                    let nid = &nodes[candidate as usize].0;
                    if let Some(node) = node_map.get(nid) {
                        if FOLD_TYPES.contains(&node.r#type.as_str()) {
                            best_split = candidate;
                            break 'outer;
                        }
                    }
                }
            }
        }

        let bottom_half = nodes.split_at(best_split as usize).1.to_vec();
        let top_half = nodes.split_at(best_split as usize).0;

        if bottom_half.is_empty() {
            continue;
        }

        max_existing_col += 1;
        let new_col = max_existing_col;
        let base_row = top_half.first().map(|(_, r)| *r).unwrap_or(0);

        for (i, (nid, _)) in bottom_half.iter().enumerate() {
            updates.push((nid.clone(), (new_col, base_row + i as i32)));
        }
    }

    for (nid, pos) in updates {
        grid.insert(nid, pos);
    }
}

fn fold_rows(
    grid: &mut HashMap<String, (i32, i32)>,
    _node_map: &HashMap<String, &KGNode>,
    _total_width: i32,
) {
    // Group nodes by row
    let mut row_nodes: HashMap<i32, Vec<(String, i32)>> = HashMap::new();
    for (nid, (c, r)) in grid.iter() {
        row_nodes.entry(*r).or_default().push((nid.clone(), *c));
    }

    let mut max_existing_row = grid.values().map(|(_, r)| *r).max().unwrap_or(0);
    let mut updates: Vec<(String, (i32, i32))> = Vec::new();

    for row in {
        let mut keys: Vec<i32> = row_nodes.keys().cloned().collect();
        keys.sort();
        keys
    } {
        let mut nodes: Vec<(String, i32)> = row_nodes[&row].clone();
        nodes.sort_by_key(|(_, c)| *c);

        if nodes.len() <= 12 {
            continue;
        }

        let mid = nodes.len() / 2;
        let right_half = nodes.split_at(mid).1.to_vec();

        max_existing_row += 1;
        let new_row = max_existing_row;
        let base_col = nodes[0].1;

        for (i, (nid, _)) in right_half.iter().enumerate() {
            updates.push((nid.clone(), (base_col + i as i32, new_row)));
        }
    }

    for (nid, pos) in updates {
        grid.insert(nid, pos);
    }
}

// ---------------------------------------------------------------------------
// Data source/consumer placement
// ---------------------------------------------------------------------------

fn place_data_sources(
    needs_ids: &HashSet<String>,
    placed: &mut HashSet<String>,
    grid: &mut HashMap<String, (i32, i32)>,
    data_adj: &HashMap<String, Vec<String>>,
) {
    let mut changed = true;
    while changed {
        changed = false;
        let unplaced: Vec<String> = needs_ids.difference(placed).cloned().collect();
        for nid in unplaced {
            let consumers: Vec<String> = data_adj
                .get(&nid)
                .map(|v| v.iter().filter(|c| placed.contains(*c)).cloned().collect())
                .unwrap_or_default();
            if consumers.is_empty() {
                continue;
            }
            let consumer_positions: Vec<(i32, i32)> = consumers
                .iter()
                .filter_map(|c| grid.get(c).copied())
                .collect();
            let min_col = consumer_positions
                .iter()
                .map(|(c, _)| *c)
                .min()
                .unwrap_or(0);
            let target_row = consumer_positions[0].1;
            let mut col = min_col - 1;
            let occupied: HashSet<(i32, i32)> = grid.values().copied().collect();
            while occupied.contains(&(col, target_row)) {
                col -= 1;
            }
            grid.insert(nid.clone(), (col, target_row));
            placed.insert(nid);
            changed = true;
        }
    }
}

fn place_data_consumers(
    needs_ids: &HashSet<String>,
    placed: &mut HashSet<String>,
    grid: &mut HashMap<String, (i32, i32)>,
    data_rev: &HashMap<String, Vec<String>>,
) {
    let mut changed = true;
    while changed {
        changed = false;
        let unplaced: Vec<String> = needs_ids.difference(placed).cloned().collect();
        for nid in unplaced {
            let sources: Vec<String> = data_rev
                .get(&nid)
                .map(|v| v.iter().filter(|s| placed.contains(*s)).cloned().collect())
                .unwrap_or_default();
            if sources.is_empty() {
                continue;
            }
            let source_positions: Vec<(i32, i32)> = sources
                .iter()
                .filter_map(|s| grid.get(s).copied())
                .collect();
            let max_col = source_positions.iter().map(|(c, _)| *c).max().unwrap_or(0);
            let target_row = source_positions[0].1;
            let mut col = max_col + 1;
            let occupied: HashSet<(i32, i32)> = grid.values().copied().collect();
            while occupied.contains(&(col, target_row)) {
                col += 1;
            }
            grid.insert(nid.clone(), (col, target_row));
            placed.insert(nid);
            changed = true;
        }
    }
}

fn place_remaining(
    needs_ids: &HashSet<String>,
    placed: &mut HashSet<String>,
    grid: &mut HashMap<String, (i32, i32)>,
) {
    let remaining: Vec<String> = needs_ids.difference(placed).cloned().collect();
    if remaining.is_empty() {
        return;
    }
    let max_row = grid.values().map(|(_, r)| *r).max().unwrap_or(0) + 1;
    for (i, nid) in remaining.iter().enumerate() {
        grid.insert(nid.clone(), (i as i32, max_row));
        placed.insert(nid.clone());
    }
}

// ---------------------------------------------------------------------------
// Grid → pixel conversion
// ---------------------------------------------------------------------------

fn shift_and_convert_to_pixels(
    grid: &HashMap<String, (i32, i32)>,
    graph: &KirGraph,
) -> Vec<KGNode> {
    if grid.is_empty() {
        return graph.nodes.clone();
    }

    let min_col = grid.values().map(|(c, _)| *c).min().unwrap_or(0);
    let min_row = grid.values().map(|(_, r)| *r).min().unwrap_or(0);

    let shifted: HashMap<String, (i32, i32)> = grid
        .iter()
        .map(|(nid, (c, r))| (nid.clone(), (c - min_col, r - min_row)))
        .collect();

    let sizes: HashMap<String, (f64, f64)> = graph
        .nodes
        .iter()
        .map(|n| (n.id.clone(), estimate_node_size(n)))
        .collect();

    let max_col_val = shifted.values().map(|(c, _)| *c).max().unwrap_or(0);
    let mut col_widths: HashMap<i32, f64> = HashMap::new();
    for (nid, (c, _)) in &shifted {
        let w = sizes.get(nid).map(|(w, _)| *w).unwrap_or(MIN_WIDTH);
        let entry = col_widths.entry(*c).or_insert(MIN_WIDTH);
        if w > *entry {
            *entry = w;
        }
    }

    let mut col_x: HashMap<i32, f64> = HashMap::new();
    let mut x = 100.0f64;
    for c in 0..=max_col_val {
        col_x.insert(c, x);
        x += col_widths.get(&c).copied().unwrap_or(MIN_WIDTH) + H_SPACING;
    }

    let mut new_nodes = Vec::new();
    for node in &graph.nodes {
        let mut new_meta = node.meta.clone();
        if let Some(&(c, r)) = shifted.get(&node.id) {
            let (w, h) = sizes
                .get(&node.id)
                .copied()
                .unwrap_or((MIN_WIDTH, MIN_HEIGHT));
            let px = *col_x.get(&c).unwrap_or(&100.0);
            let py = 100.0 + r as f64 * (MIN_HEIGHT + V_SPACING);
            new_meta.insert(
                "pos".to_string(),
                Value::List(vec![Value::Int(px as i64), Value::Int(py as i64)]),
            );
            new_meta.insert(
                "size".to_string(),
                Value::List(vec![Value::Int(w as i64), Value::Int(h as i64)]),
            );
        }
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
    new_nodes
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Assign grid positions to all nodes in `graph` that have no position.
///
/// Returns a new [`KirGraph`] with updated `meta.pos` and `meta.size` on
/// every node.  Nodes that already have a non-zero position are left as-is
/// but still appear in the returned graph.
pub fn auto_layout(graph: &KirGraph) -> KirGraph {
    if graph.nodes.is_empty() {
        return graph.clone();
    }

    let needs_layout: Vec<&KGNode> = graph
        .nodes
        .iter()
        .filter(|n| {
            !n.meta.contains_key("pos")
                || matches!(
                    n.meta.get("pos"),
                    Some(Value::List(v)) if v.len() >= 2
                        && matches!((&v[0], &v[1]), (Value::Int(0), Value::Int(0)))
                )
        })
        .collect();

    if needs_layout.is_empty() {
        return graph.clone();
    }

    let needs_ids: HashSet<String> = needs_layout.iter().map(|n| n.id.clone()).collect();
    let node_order: Vec<String> = graph
        .nodes
        .iter()
        .filter(|n| needs_ids.contains(&n.id))
        .map(|n| n.id.clone())
        .collect();
    let node_map: HashMap<String, &KGNode> =
        graph.nodes.iter().map(|n| (n.id.clone(), n)).collect();

    let (data_adj, data_rev, ctrl_adj, ctrl_rev) = build_adjacency(graph);
    let node_rank = compute_node_ranks(&node_order, &node_map, &ctrl_adj);

    let mut ctrl_nodes: HashSet<String> = HashSet::new();
    for edge in &graph.edges {
        if edge.r#type != "data" {
            if needs_ids.contains(&edge.from_node) {
                ctrl_nodes.insert(edge.from_node.clone());
            }
            if needs_ids.contains(&edge.to_node) {
                ctrl_nodes.insert(edge.to_node.clone());
            }
        }
    }

    let ctrl_roots = find_ctrl_roots(
        &node_order,
        &needs_ids,
        &ctrl_nodes,
        &ctrl_adj,
        &ctrl_rev,
        &node_rank,
        graph,
    );

    let (mut grid, mut placed) = bfs_ctrl_chain(
        &ctrl_roots,
        &ctrl_nodes,
        &needs_ids,
        &ctrl_adj,
        &node_rank,
        &node_order,
    );

    fold_grid(&mut grid, &node_map);

    place_data_sources(&needs_ids, &mut placed, &mut grid, &data_adj);
    place_data_consumers(&needs_ids, &mut placed, &mut grid, &data_rev);
    place_remaining(&needs_ids, &mut placed, &mut grid);

    let new_nodes = shift_and_convert_to_pixels(&grid, graph);
    KirGraph {
        version: graph.version.clone(),
        nodes: new_nodes,
        edges: graph.edges.clone(),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::layout::kir_to_graph;

    #[test]
    fn test_auto_layout_all_nodes_get_positions() {
        let source = r#"
x = 1
y = 2
(x, y)add(z)
(z)print()
"#;
        let graph = kir_to_graph(source).expect("parse failed");
        let laid_out = auto_layout(&graph);
        for node in &laid_out.nodes {
            let pos = node.meta.get("pos");
            assert!(
                pos.is_some(),
                "node {} has no pos after auto_layout",
                node.id
            );
        }
    }

    #[test]
    fn test_auto_layout_no_overlaps() {
        let source = r#"
a = 1
b = 2
c = 3
(a, b)add(d)
(d, c)mul(e)
(e)print()
"#;
        let graph = kir_to_graph(source).expect("parse failed");
        let laid_out = auto_layout(&graph);

        // Collect (col, row) positions
        let positions: Vec<(i64, i64)> = laid_out
            .nodes
            .iter()
            .filter_map(|n| {
                if let Some(Value::List(v)) = n.meta.get("pos") {
                    if v.len() >= 2 {
                        let x = match &v[0] {
                            Value::Int(i) => *i,
                            _ => return None,
                        };
                        let y = match &v[1] {
                            Value::Int(i) => *i,
                            _ => return None,
                        };
                        return Some((x, y));
                    }
                }
                None
            })
            .collect();

        // Check no two nodes share exact pixel position
        let pos_set: std::collections::HashSet<(i64, i64)> = positions.iter().cloned().collect();
        assert_eq!(
            positions.len(),
            pos_set.len(),
            "some nodes share the same pixel position after auto_layout"
        );
    }

    #[test]
    fn test_auto_layout_mixed_mode() {
        let source = include_str!("../../../../examples/kir_basics/mixed_mode.kir");
        let graph = kir_to_graph(source).expect("parse failed");
        let laid_out = auto_layout(&graph);
        assert_eq!(laid_out.nodes.len(), graph.nodes.len());
        for node in &laid_out.nodes {
            assert!(
                node.meta.contains_key("pos"),
                "node {} missing pos",
                node.id
            );
        }
    }

    #[test]
    fn test_estimate_node_size_reasonable() {
        let node = KGNode {
            id: "test".to_string(),
            r#type: "funcall".to_string(),
            name: "test".to_string(),
            data_inputs: vec![
                crate::kirgraph::KGPort::new("a"),
                crate::kirgraph::KGPort::new("b"),
            ],
            data_outputs: vec![crate::kirgraph::KGPort::new("out")],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: vec!["out".to_string()],
            properties: std::collections::HashMap::new(),
            meta: std::collections::HashMap::new(),
        };
        let (w, h) = estimate_node_size(&node);
        assert!(w >= MIN_WIDTH, "width too small: {}", w);
        assert!(h >= MIN_HEIGHT, "height too small: {}", h);
    }
}
