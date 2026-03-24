"""Layout quality scoring — measures wire bending cost.

Scoring model:
- Control edges: ideal = same column, 1 row below. Backward (bottom→top) = 3x penalty.
- Data edges: ideal = 1 column right, same row. Backward (right→left) = 3x penalty.
- Zero cost = perfect placement.
"""

from dataclasses import dataclass, field

from kohakunode.kirgraph.schema import KGEdge, KirGraph
from kohakunode.layout.auto_layout import estimate_node_size


@dataclass
class EdgeScore:
    edge: KGEdge
    cost: float
    col_diff: int
    row_diff: int


@dataclass
class LayoutScore:
    total: float
    max_edge_cost: float
    avg_edge_cost: float
    edge_scores: list[EdgeScore] = field(default_factory=list)


def _build_grid(graph: KirGraph) -> dict[str, tuple[int, int]]:
    """Map each node to (col, row) grid coordinates."""
    positions: dict[str, tuple[float, float]] = {}
    for node in graph.nodes:
        pos = node.meta.get("pos", [0, 0])
        positions[node.id] = (pos[0], pos[1])

    xs = sorted(set(p[0] for p in positions.values()))
    ys = sorted(set(p[1] for p in positions.values()))
    x_to_col = {x: i for i, x in enumerate(xs)}
    y_to_row = {y: i for i, y in enumerate(ys)}

    return {nid: (x_to_col[px], y_to_row[py]) for nid, (px, py) in positions.items()}


def score_edge(edge: KGEdge, grid: dict[str, tuple[int, int]]) -> float:
    """Score a single edge. 0 = ideal placement."""
    if edge.from_node not in grid or edge.to_node not in grid:
        return 0.0

    src_col, src_row = grid[edge.from_node]
    dst_col, dst_row = grid[edge.to_node]
    col_diff = dst_col - src_col
    row_diff = dst_row - src_row

    if edge.type == "control":
        # Ideal: same column (col_diff=0), 1 row below (row_diff=1)
        if row_diff < 0:
            # BACKWARD ctrl (bottom→top, e.g. loop back) = heavy penalty
            cost = abs(row_diff) * 3 + abs(col_diff) * 4
        elif row_diff == 0:
            # Same row ctrl = bad (should be vertical)
            cost = 2.0 + abs(col_diff) * 3
        else:
            # Forward ctrl
            col_penalty = abs(col_diff) * 3  # strongly penalize col deviation
            row_penalty = max(0, row_diff - 1)  # 1 row below = free
            cost = col_penalty + row_penalty
    else:
        # DATA: ideal = 1 column right (col_diff=1), same row (row_diff=0)
        if col_diff < 0:
            # BACKWARD data (right→left) = heavy penalty
            cost = abs(col_diff) * 3 + abs(row_diff) * 2
        elif col_diff == 0:
            # Same column data = mildly bad (should be horizontal)
            cost = 1.0 + abs(row_diff) * 2
        else:
            # Forward data
            col_penalty = max(0, col_diff - 1)  # 1 col right = free
            row_penalty = abs(row_diff) * 2  # strongly penalize row deviation
            cost = col_penalty + row_penalty

    return float(cost)


def score_layout(graph: KirGraph) -> LayoutScore:
    """Calculate layout quality score. Lower = better."""
    if not graph.edges:
        return LayoutScore(total=0.0, max_edge_cost=0.0, avg_edge_cost=0.0)

    grid = _build_grid(graph)

    edge_scores: list[EdgeScore] = []
    for edge in graph.edges:
        cost = score_edge(edge, grid)
        src = grid.get(edge.from_node, (0, 0))
        dst = grid.get(edge.to_node, (0, 0))
        edge_scores.append(EdgeScore(
            edge=edge, cost=cost,
            col_diff=dst[0] - src[0], row_diff=dst[1] - src[1],
        ))

    total = sum(es.cost for es in edge_scores)
    max_cost = max(es.cost for es in edge_scores)
    avg_cost = total / len(edge_scores)

    return LayoutScore(
        total=total, max_edge_cost=max_cost,
        avg_edge_cost=avg_cost, edge_scores=edge_scores,
    )
