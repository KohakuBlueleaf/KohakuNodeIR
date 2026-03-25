"""Auto-layout for KirGraph nodes — Fischer-style.

Strategy:
1. Find control flow root, place at grid (0, 0)
2. Layout control chain downward (col 0, increasing rows)
3. For each ctrl node, place data sources to the LEFT
4. Place data consumers to the RIGHT
5. Grid uses negative indices freely — shift to positive at the end
"""

from collections import defaultdict, deque

from kohakunode.kirgraph.schema import KGNode, KirGraph

CTRL_ROW_H = 18
HEADER_H = 32
DATA_ROW_H = 28
MIN_WIDTH = 180
MIN_HEIGHT = 100
H_SPACING = 60
V_SPACING = 60


def estimate_node_size(node: KGNode) -> tuple[float, float]:
    n_data = max(len(node.data_inputs), len(node.data_outputs))
    n_ci = len(node.ctrl_inputs)
    n_co = len(node.ctrl_outputs)
    w = max(MIN_WIDTH, max(n_ci, n_co) * 60 + 60)
    if node.type == "merge":
        h = (
            (CTRL_ROW_H if n_ci > 0 else 0)
            + HEADER_H
            + (CTRL_ROW_H if n_co > 0 else 0)
            + 8
        )
    else:
        h = max(
            MIN_HEIGHT,
            (CTRL_ROW_H if n_ci > 0 else 0)
            + HEADER_H
            + n_data * DATA_ROW_H
            + (CTRL_ROW_H if n_co > 0 else 0)
            + 8,
        )
    return (w, h)


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _build_adjacency(
    graph: KirGraph,
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    """Return (data_adj, data_rev, ctrl_adj, ctrl_rev) adjacency dicts."""
    data_adj: dict[str, list[str]] = defaultdict(list)
    data_rev: dict[str, list[str]] = defaultdict(list)
    ctrl_adj: dict[str, list[str]] = defaultdict(list)
    ctrl_rev: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        f, t = edge.from_node, edge.to_node
        if edge.type == "data":
            data_adj[f].append(t)
            data_rev[t].append(f)
        else:
            ctrl_adj[f].append(t)
            ctrl_rev[t].append(f)
    return data_adj, data_rev, ctrl_adj, ctrl_rev


def _compute_node_ranks(
    node_order: list[str],
    node_map: dict[str, KGNode],
    ctrl_adj: dict[str, list[str]],
) -> dict[str, float]:
    """Assign a float rank per node; merge nodes get rank just before successor."""
    node_rank: dict[str, float] = {nid: float(i) for i, nid in enumerate(node_order)}
    for nid in node_order:
        if node_map[nid].type == "merge":
            for child in ctrl_adj.get(nid, []):
                if child in node_rank:
                    node_rank[nid] = node_rank[child] - 0.5
                    break
    return node_rank


def _find_ctrl_roots(
    node_order: list[str],
    needs_ids: set[str],
    ctrl_nodes: set[str],
    ctrl_adj: dict[str, list[str]],
    ctrl_rev: dict[str, list[str]],
    node_rank: dict[str, float],
    graph: KirGraph,
) -> list[str]:
    """Identify ctrl-chain root nodes (those with no forward incoming ctrl edges)."""
    ctrl_roots = []
    for nid in node_order:
        if nid not in ctrl_nodes:
            continue
        if not ctrl_adj.get(nid):
            continue
        incoming = [s for s in ctrl_rev.get(nid, []) if s in needs_ids]
        forward_incoming = [
            s for s in incoming if node_rank.get(s, 999) < node_rank.get(nid, 0)
        ]
        if not forward_incoming:
            ctrl_roots.append(nid)

    if not ctrl_roots and ctrl_nodes:
        for nid in node_order:
            if nid in ctrl_nodes:
                return [nid]

    if not ctrl_roots:
        all_rev = {edge.to_node for edge in graph.edges}
        ctrl_roots = [nid for nid in needs_ids if nid not in all_rev]

    if not ctrl_roots:
        ctrl_roots = [node_order[0]] if node_order else []

    return ctrl_roots


def _bfs_ctrl_chain(
    ctrl_roots: list[str],
    ctrl_nodes: set[str],
    needs_ids: set[str],
    ctrl_adj: dict[str, list[str]],
    node_rank: dict[str, float],
    node_order: list[str],
) -> dict[str, tuple[int, int]]:
    """BFS from ctrl roots downward, placing nodes at column 0."""
    grid: dict[str, tuple[int, int]] = {}
    placed: set[str] = set()
    ctrl_row = 0
    ctrl_queue: deque[str] = deque()

    def bfs_from(start: str) -> None:
        nonlocal ctrl_row
        if start in placed:
            return
        grid[start] = (0, ctrl_row)
        placed.add(start)
        ctrl_queue.append(start)
        ctrl_row += 1
        while ctrl_queue:
            nid = ctrl_queue.popleft()
            for child in ctrl_adj.get(nid, []):
                if child not in needs_ids or child in placed:
                    continue
                if node_rank.get(child, 999) < node_rank.get(nid, 0):
                    continue
                grid[child] = (0, ctrl_row)
                placed.add(child)
                ctrl_queue.append(child)
                ctrl_row += 1

    if ctrl_roots:
        bfs_from(ctrl_roots[0])

    for nid in node_order:
        if nid in ctrl_nodes and nid not in placed and nid in needs_ids:
            bfs_from(nid)

    return grid, placed


FOLD_TYPES = {"branch", "merge", "switch", "parallel"}


def _fold_grid(
    grid: dict[str, tuple[int, int]],
    node_map: dict[str, "KGNode"],
) -> None:
    """Fold the grid to target roughly 3:2 (col:row) aspect ratio.

    Strategy:
    1. Measure current grid dimensions
    2. If too tall: split long columns vertically, concat halves horizontally
       - Prefer splitting at control flow nodes (branch, merge, switch, parallel)
    3. If too wide: split long rows horizontally, concat halves vertically
       - Higher threshold (rows can be wider than columns are tall)
    """
    if not grid:
        return

    # Measure current dimensions
    max_col = max(c for c, _ in grid.values())
    min_col = min(c for c, _ in grid.values())
    max_row = max(r for _, r in grid.values())
    min_row = min(r for _, r in grid.values())
    width = max_col - min_col + 1
    height = max_row - min_row + 1

    if height <= 8 and width <= 12:
        return  # Already compact enough

    # Target aspect ratio: prefer wider than tall (3:2)
    # If height > width * 2, fold columns
    if height > max(8, width * 2):
        _fold_columns(grid, node_map, height)

    # Recompute after column folding
    if grid:
        max_row = max(r for _, r in grid.values())
        min_row = min(r for _, r in grid.values())
        max_col = max(c for c, _ in grid.values())
        min_col = min(c for c, _ in grid.values())
        width = max_col - min_col + 1
        height = max_row - min_row + 1

    # If width > height * 3, fold rows (higher threshold)
    if width > max(12, height * 3):
        _fold_rows(grid, node_map, width)


def _fold_columns(
    grid: dict[str, tuple[int, int]],
    node_map: dict[str, "KGNode"],
    total_height: int,
) -> None:
    """Split tall columns: take the bottom half and place it as a new column to the right."""
    # Group nodes by column
    col_nodes: dict[int, list[tuple[str, int]]] = {}
    for nid, (c, r) in grid.items():
        col_nodes.setdefault(c, []).append((nid, r))

    # Process each column
    col_offset = 0  # How many new columns we've added
    max_existing_col = max(c for c, _ in grid.values())

    for col in sorted(col_nodes.keys()):
        nodes = sorted(col_nodes[col], key=lambda x: x[1])
        if len(nodes) <= 8:
            continue

        # Find best split point — prefer control flow nodes near the middle
        mid = len(nodes) // 2
        best_split = mid

        # Search around the middle for a control flow fold point
        for offset in range(len(nodes) // 4):
            for candidate in [mid + offset, mid - offset]:
                if 0 < candidate < len(nodes):
                    nid = nodes[candidate][0]
                    node = node_map.get(nid)
                    if node and node.type in FOLD_TYPES:
                        best_split = candidate
                        break
            else:
                continue
            break

        # Split: top half stays, bottom half moves to new column
        top_half = nodes[:best_split]
        bottom_half = nodes[best_split:]

        if not bottom_half:
            continue

        # Place bottom half in a new column to the right of everything
        max_existing_col += 1
        new_col = max_existing_col
        base_row = top_half[0][1] if top_half else 0  # Align top of new column

        for i, (nid, _old_row) in enumerate(bottom_half):
            grid[nid] = (new_col, base_row + i)


def _fold_rows(
    grid: dict[str, tuple[int, int]],
    node_map: dict[str, "KGNode"],
    total_width: int,
) -> None:
    """Split wide rows: take the right half and place it as new rows below."""
    # Group nodes by row
    row_nodes: dict[int, list[tuple[str, int]]] = {}
    for nid, (c, r) in grid.items():
        row_nodes.setdefault(r, []).append((nid, c))

    max_existing_row = max(r for _, r in grid.values())

    for row in sorted(row_nodes.keys()):
        nodes = sorted(row_nodes[row], key=lambda x: x[1])
        if len(nodes) <= 12:
            continue

        mid = len(nodes) // 2
        right_half = nodes[mid:]

        max_existing_row += 1
        new_row = max_existing_row
        base_col = nodes[0][1]

        for i, (nid, _old_col) in enumerate(right_half):
            grid[nid] = (base_col + i, new_row)


def _place_data_sources(
    needs_ids: set[str],
    placed: set[str],
    grid: dict[str, tuple[int, int]],
    data_adj: dict[str, list[str]],
) -> None:
    """Place data-source nodes to the LEFT of their consumers (in-place)."""
    changed = True
    while changed:
        changed = False
        for nid in list(needs_ids - placed):
            consumers = [c for c in data_adj.get(nid, []) if c in placed]
            if not consumers:
                continue
            consumer_positions = [grid[c] for c in consumers]
            min_col = min(p[0] for p in consumer_positions)
            target_row = consumer_positions[0][1]
            col = min_col - 1
            occupied = set(grid.values())
            while (col, target_row) in occupied:
                col -= 1
            grid[nid] = (col, target_row)
            placed.add(nid)
            changed = True


def _place_data_consumers(
    needs_ids: set[str],
    placed: set[str],
    grid: dict[str, tuple[int, int]],
    data_rev: dict[str, list[str]],
) -> None:
    """Place data-consumer nodes to the RIGHT of their sources (in-place)."""
    changed = True
    while changed:
        changed = False
        for nid in list(needs_ids - placed):
            sources = [s for s in data_rev.get(nid, []) if s in placed]
            if not sources:
                continue
            source_positions = [grid[s] for s in sources]
            max_col = max(p[0] for p in source_positions)
            target_row = source_positions[0][1]
            col = max_col + 1
            occupied = set(grid.values())
            while (col, target_row) in occupied:
                col += 1
            grid[nid] = (col, target_row)
            placed.add(nid)
            changed = True


def _place_remaining(
    needs_ids: set[str],
    placed: set[str],
    grid: dict[str, tuple[int, int]],
) -> None:
    """Place any still-unplaced nodes in a new row below everything else."""
    remaining = needs_ids - placed
    if not remaining:
        return
    max_row = max((r for _, r in grid.values()), default=0) + 1
    for i, nid in enumerate(remaining):
        grid[nid] = (i, max_row)
        placed.add(nid)


def _shift_and_convert_to_pixels(
    grid: dict[str, tuple[int, int]],
    graph: KirGraph,
) -> list[KGNode]:
    """Shift grid so min col/row = 0, compute pixel positions, return new nodes."""
    if not grid:
        return list(graph.nodes)

    min_col = min(c for c, r in grid.values())
    min_row = min(r for c, r in grid.values())
    shifted = {nid: (c - min_col, r - min_row) for nid, (c, r) in grid.items()}

    sizes: dict[str, tuple[float, float]] = {
        node.id: estimate_node_size(node) for node in graph.nodes
    }

    max_col_val = max((c for c, r in shifted.values()), default=0)
    col_widths: dict[int, float] = {}
    for nid, (c, _r) in shifted.items():
        w = sizes[nid][0]
        col_widths[c] = max(col_widths.get(c, MIN_WIDTH), w)

    col_x: dict[int, float] = {}
    x = 100.0
    for c in range(max_col_val + 1):
        col_x[c] = x
        x += col_widths.get(c, MIN_WIDTH) + H_SPACING

    new_nodes = []
    for node in graph.nodes:
        new_meta = dict(node.meta)
        if node.id in shifted:
            c, r = shifted[node.id]
            w, h = sizes[node.id]
            new_meta["pos"] = [
                int(col_x.get(c, 100)),
                int(100 + r * (MIN_HEIGHT + V_SPACING)),
            ]
            new_meta["size"] = [int(w), int(h)]
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
    return new_nodes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def auto_layout(graph: KirGraph) -> KirGraph:
    if not graph.nodes:
        return graph

    needs_layout = [
        n
        for n in graph.nodes
        if n.meta.get("pos", [0, 0]) == [0, 0] or "pos" not in n.meta
    ]
    if not needs_layout:
        return graph

    needs_ids = set(n.id for n in needs_layout)
    node_order = [n.id for n in graph.nodes if n.id in needs_ids]
    node_map = {n.id: n for n in graph.nodes}

    data_adj, data_rev, ctrl_adj, ctrl_rev = _build_adjacency(graph)
    node_rank = _compute_node_ranks(node_order, node_map, ctrl_adj)

    ctrl_nodes: set[str] = set()
    for edge in graph.edges:
        if edge.type != "data":
            if edge.from_node in needs_ids:
                ctrl_nodes.add(edge.from_node)
            if edge.to_node in needs_ids:
                ctrl_nodes.add(edge.to_node)

    ctrl_roots = _find_ctrl_roots(
        node_order, needs_ids, ctrl_nodes, ctrl_adj, ctrl_rev, node_rank, graph
    )

    grid, placed = _bfs_ctrl_chain(
        ctrl_roots, ctrl_nodes, needs_ids, ctrl_adj, node_rank, node_order
    )

    # Fold the grid to target a reasonable aspect ratio
    _fold_grid(grid, node_map)

    _place_data_sources(needs_ids, placed, grid, data_adj)
    _place_data_consumers(needs_ids, placed, grid, data_rev)
    _place_remaining(needs_ids, placed, grid)

    new_nodes = _shift_and_convert_to_pixels(grid, graph)
    return KirGraph(version=graph.version, nodes=new_nodes, edges=graph.edges)
