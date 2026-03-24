"""Layout quality scoring for KirGraph — measures wire bending cost.

Each node is mapped to a (col, row) grid cell derived from its pixel
position and estimated size.  Edges are scored by deviation from their
ideal direction:

* **Control edges** should flow top-to-bottom within the same column.
* **Data edges** should flow left-to-right within the same row.

Total score = sum of all edge costs.  Lower is better; 0 is perfect.
"""

from dataclasses import dataclass, field

from kohakunode.kirgraph.schema import KGEdge, KGNode, KirGraph
from kohakunode.layout.auto_layout import (
    H_SPACING,
    MIN_HEIGHT,
    MIN_WIDTH,
    V_SPACING,
    estimate_node_size,
)


@dataclass
class EdgeScore:
    """Detailed score for a single edge."""

    edge: KGEdge
    cost: float
    col_diff: int
    row_diff: int


@dataclass
class LayoutScore:
    """Aggregate layout quality report."""

    total: float
    max_edge_cost: float
    avg_edge_cost: float
    edge_scores: list[EdgeScore] = field(default_factory=list)


def _build_grid(
    graph: KirGraph,
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[float, float]]]:
    """Map each node to (col, row) grid coordinates and collect sizes.

    Grid assignment works by sorting the unique x positions into column
    indices and unique y positions into row indices, so the mapping is
    purely topological rather than metric.
    """
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

    # Build column and row indices from sorted unique coordinates
    xs = sorted(set(p[0] for p in positions.values()))
    ys = sorted(set(p[1] for p in positions.values()))
    x_to_col = {x: i for i, x in enumerate(xs)}
    y_to_row = {y: i for i, y in enumerate(ys)}

    grid: dict[str, tuple[int, int]] = {}
    for nid, (px, py) in positions.items():
        grid[nid] = (x_to_col[px], y_to_row[py])

    return grid, sizes


def score_edge(
    edge: KGEdge,
    node_positions: dict[str, tuple[int, int]],
    node_sizes: dict[str, tuple[float, float]],
) -> float:
    """Score a single edge by its deviation from the ideal direction.

    Parameters
    ----------
    edge : KGEdge
        The edge to score.
    node_positions : dict
        Mapping of node id -> (col, row) grid cell.
    node_sizes : dict
        Mapping of node id -> (width, height) in pixels (unused in the
        grid model but available for future refinement).

    Returns
    -------
    float
        Cost for this edge.  0 = ideal placement.
    """
    if edge.from_node not in node_positions or edge.to_node not in node_positions:
        return 0.0

    src_col, src_row = node_positions[edge.from_node]
    dst_col, dst_row = node_positions[edge.to_node]
    col_diff = dst_col - src_col
    row_diff = dst_row - src_row

    if edge.type == "control":
        # Control: ideal = same column, target 1 row below
        if row_diff < 0:
            # Backward (loop) edge
            cost = abs(row_diff) + abs(col_diff) * 3
        else:
            cost = abs(col_diff) * 2 + max(0, abs(row_diff) - 1)
    else:
        # Data: ideal = target 1 column right, same row
        if col_diff < 0:
            # Backward data edge
            cost = abs(col_diff) * 3 + abs(row_diff)
        else:
            cost = max(0, abs(col_diff) - 1) + abs(row_diff) * 2

    return float(cost)


def score_layout(graph: KirGraph) -> LayoutScore:
    """Calculate layout quality score.  Lower = better.

    Returns a ``LayoutScore`` with per-edge breakdown.
    """
    if not graph.edges:
        return LayoutScore(total=0.0, max_edge_cost=0.0, avg_edge_cost=0.0)

    grid, sizes = _build_grid(graph)

    edge_scores: list[EdgeScore] = []
    for edge in graph.edges:
        cost = score_edge(edge, grid, sizes)
        src = grid.get(edge.from_node, (0, 0))
        dst = grid.get(edge.to_node, (0, 0))
        edge_scores.append(
            EdgeScore(
                edge=edge,
                cost=cost,
                col_diff=dst[0] - src[0],
                row_diff=dst[1] - src[1],
            )
        )

    total = sum(es.cost for es in edge_scores)
    max_cost = max(es.cost for es in edge_scores)
    avg_cost = total / len(edge_scores)

    return LayoutScore(
        total=total,
        max_edge_cost=max_cost,
        avg_edge_cost=avg_cost,
        edge_scores=edge_scores,
    )
