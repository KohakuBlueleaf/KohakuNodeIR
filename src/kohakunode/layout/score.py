"""Layout quality scoring for KirGraph — measures wire bending cost.

Each node is mapped to a (col, row) grid cell derived from its pixel
position and estimated size.  Edges are scored by deviation from their
ideal direction:

* **Control edges** should flow top-to-bottom within the same column.
  - Same column, row_diff=1: 0 cost (perfect).
  - Backward (bottom-to-top): 3x penalty.

* **Data edges** should flow left-to-right within the same row.
  - Same row, col_diff=1: 0 cost (perfect).
  - Backward (right-to-left): 3x penalty.

Additional penalties:
* **Edge crossings**: approximate crossing count between adjacent columns.
* **Node overlap**: penalty for nodes sharing the same grid cell.

Total score = sum of all edge costs + crossing penalty + overlap penalty.
Lower is better; 0 is perfect.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from kohakunode.kirgraph.schema import KGEdge, KGNode, KirGraph
from kohakunode.layout.auto_layout import estimate_node_size

# Tuning constants
CROSSING_PENALTY = 2.0  # cost per edge crossing
OVERLAP_PENALTY = 10.0  # cost per pair of overlapping nodes


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
    crossing_penalty: float = 0.0
    overlap_penalty: float = 0.0


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
    grid: dict[str, tuple[int, int]],
) -> float:
    """Score a single edge by its deviation from the ideal direction.

    Parameters
    ----------
    edge : KGEdge
        The edge to score.
    grid : dict
        Mapping of node id -> (col, row) grid cell.

    Returns
    -------
    float
        Cost for this edge.  0 = ideal placement.
    """
    if edge.from_node not in grid or edge.to_node not in grid:
        return 0.0

    src_col, src_row = grid[edge.from_node]
    dst_col, dst_row = grid[edge.to_node]
    col_diff = dst_col - src_col
    row_diff = dst_row - src_row

    if edge.type == "control":
        # Control: ideal = same column (col_diff=0), target 1 row below
        # (row_diff=1).  Perfect placement = 0 cost.
        if row_diff < 0:
            # BACKWARD ctrl edge (bottom -> top, e.g. loop back)
            # 3x penalty on both axes
            cost = abs(row_diff) * 3 + abs(col_diff) * 3
        elif row_diff == 0:
            # Same row ctrl = bad (control should be vertical)
            cost = 2.0 + abs(col_diff) * 3
        else:
            # Forward ctrl: col deviation strongly penalised, row_diff=1 free
            col_penalty = abs(col_diff) * 3
            row_penalty = max(0, row_diff - 1)
            cost = col_penalty + row_penalty
    else:
        # Data: ideal = target 1 column right (col_diff=1), same row
        # (row_diff=0).  Perfect placement = 0 cost.
        if col_diff < 0:
            # BACKWARD data edge (right -> left)
            # 3x penalty on both axes
            cost = abs(col_diff) * 3 + abs(row_diff) * 2
        elif col_diff == 0:
            # Same column data = mildly bad (should be horizontal)
            cost = 1.0 + abs(row_diff) * 2
        else:
            # Forward data: row deviation strongly penalised, col_diff=1 free
            col_penalty = max(0, col_diff - 1)
            row_penalty = abs(row_diff) * 2
            cost = col_penalty + row_penalty

    return float(cost)


def _count_crossings(
    grid: dict[str, tuple[int, int]],
    edges: list[KGEdge],
) -> int:
    """Approximate the number of edge crossings.

    For each pair of adjacent columns, collect edges that span between
    them (directly or passing through).  Two edges (a->b) and (c->d)
    cross if and only if the source ordering and target ordering are
    inverted — i.e., one edge's source is above the other's but its
    target is below (or vice-versa).

    This is equivalent to counting inversions, solvable in
    O(|E| log |V|) via merge-sort.  For simplicity, we use the O(E^2)
    pairwise check per column-pair, which is fine for typical graph
    sizes (< 200 edges between any column pair).
    """
    # Group edges by the column-pair they span
    # For edges spanning multiple columns, count at each intermediate pair
    col_pair_edges: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)

    for edge in edges:
        if edge.from_node not in grid or edge.to_node not in grid:
            continue
        src_col, src_row = grid[edge.from_node]
        dst_col, dst_row = grid[edge.to_node]

        if src_col == dst_col:
            continue  # vertical edges within same column don't cross horizontally

        # Normalise direction: always left-to-right for crossing detection
        if src_col > dst_col:
            src_col, src_row, dst_col, dst_row = dst_col, dst_row, src_col, src_row

        # For multi-column spans, interpolate row at each column boundary
        span = dst_col - src_col
        for step in range(span):
            left_col = src_col + step
            right_col = left_col + 1
            # Linear interpolation of row position at column boundaries
            t_left = step / span
            t_right = (step + 1) / span
            row_left = src_row + t_left * (dst_row - src_row)
            row_right = src_row + t_right * (dst_row - src_row)
            col_pair_edges[(left_col, right_col)].append((row_left, row_right))

    # Count crossings per column-pair
    total_crossings = 0
    for pair_edges in col_pair_edges.values():
        n = len(pair_edges)
        if n < 2:
            continue
        # Pairwise crossing check: edges (a_left, a_right) and (b_left, b_right)
        # cross iff (a_left < b_left and a_right > b_right) or vice-versa
        for i in range(n):
            for j in range(i + 1, n):
                a_left, a_right = pair_edges[i]
                b_left, b_right = pair_edges[j]
                if (a_left < b_left and a_right > b_right) or (
                    a_left > b_left and a_right < b_right
                ):
                    total_crossings += 1

    return total_crossings


def _count_overlaps(grid: dict[str, tuple[int, int]]) -> int:
    """Count pairs of nodes occupying the same grid cell."""
    cell_counts: dict[tuple[int, int], int] = defaultdict(int)
    for pos in grid.values():
        cell_counts[pos] += 1

    overlaps = 0
    for count in cell_counts.values():
        if count > 1:
            # C(count, 2) = number of overlapping pairs
            overlaps += count * (count - 1) // 2

    return overlaps


def score_layout(graph: KirGraph) -> LayoutScore:
    """Calculate layout quality score.  Lower = better.

    Returns a ``LayoutScore`` with per-edge breakdown plus crossing and
    overlap penalties.
    """
    if not graph.edges:
        return LayoutScore(total=0.0, max_edge_cost=0.0, avg_edge_cost=0.0)

    grid, sizes = _build_grid(graph)

    edge_scores: list[EdgeScore] = []
    for edge in graph.edges:
        cost = score_edge(edge, grid)
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

    edge_total = sum(es.cost for es in edge_scores)
    max_cost = max(es.cost for es in edge_scores)
    avg_cost = edge_total / len(edge_scores)

    # Edge crossing penalty
    crossings = _count_crossings(grid, graph.edges)
    crossing_cost = crossings * CROSSING_PENALTY

    # Node overlap penalty
    overlaps = _count_overlaps(grid)
    overlap_cost = overlaps * OVERLAP_PENALTY

    total = edge_total + crossing_cost + overlap_cost

    return LayoutScore(
        total=total,
        max_edge_cost=max_cost,
        avg_edge_cost=avg_cost,
        edge_scores=edge_scores,
        crossing_penalty=crossing_cost,
        overlap_penalty=overlap_cost,
    )
