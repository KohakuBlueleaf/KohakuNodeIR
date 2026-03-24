"""Layout optimizer for KirGraph — local-search placement improvement.

Starts from the auto-layout result and iteratively improves it by
trying swaps, column moves, and row shifts that reduce the total
layout score (wire-bending cost).

The grid is *sparse* — nodes may sit anywhere; there is no requirement
to pack them into a dense rectangle.
"""

import copy
from collections import defaultdict

from kohakunode.kirgraph.schema import KGEdge, KGNode, KirGraph
from kohakunode.layout.auto_layout import (
    H_SPACING,
    MIN_HEIGHT,
    MIN_WIDTH,
    V_SPACING,
    auto_layout,
    estimate_node_size,
)
from kohakunode.layout.score import score_edge


def _grid_from_graph(
    graph: KirGraph,
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[float, float]]]:
    """Extract (col, row) grid positions and pixel sizes for every node."""
    positions: dict[str, tuple[float, float]] = {}
    sizes: dict[str, tuple[float, float]] = {}

    for node in graph.nodes:
        pos = node.meta.get("pos", [0, 0])
        positions[node.id] = (pos[0], pos[1])
        w, h = estimate_node_size(node)
        if "size" in node.meta:
            s = node.meta["size"]
            if isinstance(s, (list, tuple)) and len(s) >= 2:
                w = max(w, s[0])
                h = max(h, s[1])
        sizes[node.id] = (w, h)

    xs = sorted(set(p[0] for p in positions.values()))
    ys = sorted(set(p[1] for p in positions.values()))
    x_to_col = {x: i for i, x in enumerate(xs)}
    y_to_row = {y: i for i, y in enumerate(ys)}

    grid: dict[str, tuple[int, int]] = {}
    for nid, (px, py) in positions.items():
        grid[nid] = (x_to_col[px], y_to_row[py])

    return grid, sizes


def _total_score(
    grid: dict[str, tuple[int, int]],
    sizes: dict[str, tuple[float, float]],
    edges: list[KGEdge],
) -> float:
    """Sum of all edge costs for the current grid assignment."""
    return sum(score_edge(e, grid, sizes) for e in edges)


def _apply_grid_to_graph(
    graph: KirGraph,
    grid: dict[str, tuple[int, int]],
    sizes: dict[str, tuple[float, float]],
) -> KirGraph:
    """Convert grid assignments back to pixel coordinates in a new graph."""
    # Determine pixel offsets per column and row
    cols_used: dict[int, list[str]] = defaultdict(list)
    rows_used: dict[int, list[str]] = defaultdict(list)
    for nid, (c, r) in grid.items():
        cols_used[c].append(nid)
        rows_used[r].append(nid)

    # Column x-offsets based on max width in each column
    sorted_cols = sorted(cols_used.keys())
    col_x: dict[int, float] = {}
    x = 100.0
    for c in sorted_cols:
        col_x[c] = x
        max_w = max((sizes[nid][0] for nid in cols_used[c]), default=MIN_WIDTH)
        x += max_w + H_SPACING

    # Row y-offsets based on max height in each row
    sorted_rows = sorted(rows_used.keys())
    row_y: dict[int, float] = {}
    y = 100.0
    for r in sorted_rows:
        row_y[r] = y
        max_h = max((sizes[nid][1] for nid in rows_used[r]), default=MIN_HEIGHT)
        y += max_h + V_SPACING

    new_nodes: list[KGNode] = []
    for node in graph.nodes:
        c, r = grid[node.id]
        new_meta = dict(node.meta)
        new_meta["pos"] = [int(col_x[c]), int(row_y[r])]
        new_meta["size"] = [int(sizes[node.id][0]), int(sizes[node.id][1])]
        new_nodes.append(
            KGNode(
                id=node.id,
                type=node.type,
                name=node.name,
                data_inputs=node.data_inputs,
                data_outputs=node.data_outputs,
                ctrl_inputs=node.ctrl_inputs,
                ctrl_outputs=node.ctrl_outputs,
                properties=node.properties,
                meta=new_meta,
            )
        )

    return KirGraph(version=graph.version, nodes=new_nodes, edges=graph.edges)


def optimize_layout(graph: KirGraph, max_iterations: int = 100) -> KirGraph:
    """Improve layout by swapping/moving nodes to minimize score.

    1. Start from ``auto_layout`` result.
    2. Build grid assignments (col, row for each node).
    3. On each iteration, try local moves and accept improvements.
    4. Stop when no improvement found or *max_iterations* exhausted.

    Returns a new ``KirGraph`` with optimized positions.
    """
    # Ensure we have a starting layout
    graph = auto_layout(graph)
    grid, sizes = _grid_from_graph(graph)
    edges = graph.edges
    node_ids = list(grid.keys())

    if len(node_ids) <= 1 or not edges:
        return graph

    best_score = _total_score(grid, sizes, edges)

    for _iteration in range(max_iterations):
        improved = False

        # --- Strategy A: swap two nodes within the same column ---
        cols: dict[int, list[str]] = defaultdict(list)
        for nid, (c, r) in grid.items():
            cols[c].append(nid)

        for col_nodes in cols.values():
            if len(col_nodes) < 2:
                continue
            for i in range(len(col_nodes)):
                for j in range(i + 1, len(col_nodes)):
                    a, b = col_nodes[i], col_nodes[j]
                    # Swap rows
                    grid[a], grid[b] = (
                        (grid[a][0], grid[b][1]),
                        (grid[b][0], grid[a][1]),
                    )
                    new_score = _total_score(grid, sizes, edges)
                    if new_score < best_score:
                        best_score = new_score
                        improved = True
                    else:
                        # Revert
                        grid[a], grid[b] = (
                            (grid[a][0], grid[b][1]),
                            (grid[b][0], grid[a][1]),
                        )

        # --- Strategy B: move a node to an adjacent column ---
        for nid in node_ids:
            old_col, old_row = grid[nid]
            for delta_c in (-1, 1):
                new_col = old_col + delta_c
                if new_col < 0:
                    continue
                grid[nid] = (new_col, old_row)
                new_score = _total_score(grid, sizes, edges)
                if new_score < best_score:
                    best_score = new_score
                    improved = True
                else:
                    grid[nid] = (old_col, old_row)

        # --- Strategy C: move a node to an adjacent row ---
        for nid in node_ids:
            old_col, old_row = grid[nid]
            for delta_r in (-1, 1):
                new_row = old_row + delta_r
                if new_row < 0:
                    continue
                grid[nid] = (old_col, new_row)
                new_score = _total_score(grid, sizes, edges)
                if new_score < best_score:
                    best_score = new_score
                    improved = True
                else:
                    grid[nid] = (old_col, old_row)

        if not improved:
            break

    return _apply_grid_to_graph(graph, grid, sizes)
