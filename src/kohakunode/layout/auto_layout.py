"""Auto-layout for KirGraph nodes — Fischer-style.

Strategy:
1. Find control flow root, place at grid (0, 0)
2. Layout control chain downward (col 0, increasing rows)
3. For each ctrl node, place data sources to the LEFT
4. Place data consumers to the RIGHT
5. Grid uses negative indices freely — shift to positive at the end
"""

from collections import defaultdict, deque
from dataclasses import dataclass

from kohakunode.kirgraph.schema import KGNode, KirGraph

CTRL_ROW_H = 18
HEADER_H = 32
DATA_ROW_H = 28
MIN_WIDTH = 180
MIN_HEIGHT = 100
H_SPACING = 60
V_SPACING = 40


def estimate_node_size(node: KGNode) -> tuple[float, float]:
    n_data = max(len(node.data_inputs), len(node.data_outputs))
    n_ci = len(node.ctrl_inputs)
    n_co = len(node.ctrl_outputs)
    w = max(MIN_WIDTH, max(n_ci, n_co) * 60 + 60)
    h = max(MIN_HEIGHT,
            (CTRL_ROW_H if n_ci > 0 else 0) + HEADER_H +
            n_data * DATA_ROW_H +
            (CTRL_ROW_H if n_co > 0 else 0) + 8)
    return (w, h)


def auto_layout(graph: KirGraph) -> KirGraph:
    if not graph.nodes:
        return graph

    # Check which nodes need layout
    needs_layout = [n for n in graph.nodes if n.meta.get("pos", [0, 0]) == [0, 0] or "pos" not in n.meta]
    if not needs_layout:
        return graph

    needs_ids = set(n.id for n in needs_layout)

    # Build adjacency
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

    # Grid: node_id → (col, row) — negative indices allowed
    grid: dict[str, tuple[int, int]] = {}
    placed: set[str] = set()

    # ── Step 1: Find ctrl root and layout ctrl chain at col=0 ──
    # Ctrl root = node with ctrl outputs but no ctrl inputs (in needs set)
    ctrl_roots = [nid for nid in needs_ids
                  if ctrl_adj.get(nid) and not any(s in needs_ids for s in ctrl_rev.get(nid, []))]

    if not ctrl_roots:
        # No ctrl chain — find any root (no incoming edges at all)
        all_rev = set()
        for edge in graph.edges:
            all_rev.add(edge.to_node)
        ctrl_roots = [nid for nid in needs_ids if nid not in all_rev]
    if not ctrl_roots:
        ctrl_roots = [list(needs_ids)[0]]

    # BFS ctrl chain downward from root at (0, 0)
    ctrl_row = 0
    ctrl_queue = deque()
    for r in ctrl_roots:
        if r not in placed:
            grid[r] = (0, ctrl_row)
            placed.add(r)
            ctrl_queue.append(r)
            ctrl_row += 1

    while ctrl_queue:
        nid = ctrl_queue.popleft()
        for child in ctrl_adj.get(nid, []):
            if child in needs_ids and child not in placed:
                grid[child] = (0, ctrl_row)
                placed.add(child)
                ctrl_queue.append(child)
                ctrl_row += 1

    # ── Step 2: Place data sources LEFT of their consumers ──
    # BFS from placed nodes, going backward through data edges
    changed = True
    while changed:
        changed = False
        for nid in list(needs_ids - placed):
            # Check if any of this node's data consumers are placed
            consumers = [c for c in data_adj.get(nid, []) if c in placed]
            if consumers:
                # Place to the LEFT of the leftmost consumer, same row
                consumer_positions = [grid[c] for c in consumers]
                min_col = min(p[0] for p in consumer_positions)
                target_row = consumer_positions[0][1]  # same row as first consumer
                # Find a free cell
                col = min_col - 1
                while (col, target_row) in {v for v in grid.values()}:
                    col -= 1
                grid[nid] = (col, target_row)
                placed.add(nid)
                changed = True

    # ── Step 3: Place data consumers RIGHT of their sources ──
    changed = True
    while changed:
        changed = False
        for nid in list(needs_ids - placed):
            sources = [s for s in data_rev.get(nid, []) if s in placed]
            if sources:
                source_positions = [grid[s] for s in sources]
                max_col = max(p[0] for p in source_positions)
                target_row = source_positions[0][1]
                col = max_col + 1
                while (col, target_row) in {v for v in grid.values()}:
                    col += 1
                grid[nid] = (col, target_row)
                placed.add(nid)
                changed = True

    # ── Step 4: Place remaining unconnected nodes ──
    remaining = needs_ids - placed
    if remaining:
        max_row = max((r for _, r in grid.values()), default=0) + 1
        for i, nid in enumerate(remaining):
            grid[nid] = (i, max_row)
            placed.add(nid)

    # ── Step 5: Shift grid so min col/row = 0, convert to pixels ──
    if grid:
        min_col = min(c for c, r in grid.values())
        min_row = min(r for c, r in grid.values())
        shifted = {nid: (c - min_col, r - min_row) for nid, (c, r) in grid.items()}
    else:
        shifted = {}

    # Compute sizes
    sizes: dict[str, tuple[float, float]] = {}
    for node in graph.nodes:
        sizes[node.id] = estimate_node_size(node)

    # Column widths for pixel conversion
    max_col_val = max((c for c, r in shifted.values()), default=0)
    col_widths: dict[int, float] = {}
    for nid, (c, r) in shifted.items():
        w = sizes[nid][0]
        col_widths[c] = max(col_widths.get(c, MIN_WIDTH), w)

    # Compute x offsets per column
    col_x: dict[int, float] = {}
    x = 100
    for c in range(max_col_val + 1):
        col_x[c] = x
        x += col_widths.get(c, MIN_WIDTH) + H_SPACING

    # Build output
    new_nodes = []
    for node in graph.nodes:
        new_meta = dict(node.meta)
        if node.id in shifted:
            c, r = shifted[node.id]
            w, h = sizes[node.id]
            new_meta["pos"] = [int(col_x.get(c, 100)), int(100 + r * (MIN_HEIGHT + V_SPACING))]
            new_meta["size"] = [int(w), int(h)]
        new_nodes.append(KGNode(
            id=node.id, type=node.type, name=node.name,
            data_inputs=node.data_inputs, data_outputs=node.data_outputs,
            ctrl_inputs=node.ctrl_inputs, ctrl_outputs=node.ctrl_outputs,
            properties=node.properties, meta=new_meta,
        ))

    return KirGraph(version=graph.version, nodes=new_nodes, edges=graph.edges)
