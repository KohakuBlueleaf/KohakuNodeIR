"""Auto-layout for KirGraph nodes — Fischer-style placement.

Column assignment: DATA edges only (left → right).
Row assignment: CTRL edges only (top → bottom within each column).
Value nodes: placed adjacent to their first consumer.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field

from kohakunode.kirgraph.schema import KGNode, KirGraph

CTRL_ROW_H = 18
HEADER_H = 32
DATA_ROW_H = 28
MIN_WIDTH = 180
MIN_HEIGHT = 100
H_SPACING = 60
V_SPACING = 40


@dataclass
class LayoutNode:
    id: str
    width: float = 0.0
    height: float = 0.0
    x: float = 0.0
    y: float = 0.0
    layer: int = -1
    order: int = 0
    has_position: bool = False
    data_in_count: int = 0
    data_out_count: int = 0
    ctrl_in_count: int = 0
    ctrl_out_count: int = 0


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
    """Assign positions to nodes without @meta position info."""
    lnodes: dict[str, LayoutNode] = {}
    for node in graph.nodes:
        pos = node.meta.get("pos", [0, 0])
        has_pos = pos is not None and pos != [0, 0]
        w, h = estimate_node_size(node)
        if "size" in node.meta:
            s = node.meta["size"]
            if isinstance(s, (list, tuple)) and len(s) >= 2:
                w = max(w, s[0])
                h = max(h, s[1])
        lnodes[node.id] = LayoutNode(
            id=node.id, width=w, height=h,
            x=pos[0] if has_pos else 0, y=pos[1] if has_pos else 0,
            has_position=has_pos,
            data_in_count=len(node.data_inputs),
            data_out_count=len(node.data_outputs),
            ctrl_in_count=len(node.ctrl_inputs),
            ctrl_out_count=len(node.ctrl_outputs),
        )

    needs = {nid: ln for nid, ln in lnodes.items() if not ln.has_position}
    if not needs:
        return graph

    # Build adjacency — SEPARATE data and ctrl
    data_adj: dict[str, list[str]] = defaultdict(list)
    data_rev: dict[str, list[str]] = defaultdict(list)
    ctrl_adj: dict[str, list[str]] = defaultdict(list)
    ctrl_rev: dict[str, list[str]] = defaultdict(list)

    for edge in graph.edges:
        if edge.type == "data":
            data_adj[edge.from_node].append(edge.to_node)
            data_rev[edge.to_node].append(edge.from_node)
        else:
            ctrl_adj[edge.from_node].append(edge.to_node)
            ctrl_rev[edge.to_node].append(edge.from_node)

    node_ids = list(needs.keys())

    # ── Step 1: Column assignment using DATA edges only ──
    # Nodes with no data input = column 0
    # Others = max(source columns) + 1
    col: dict[str, int] = {}
    data_roots = [nid for nid in node_ids if not data_rev.get(nid)]
    if not data_roots:
        data_roots = node_ids[:1]

    # BFS longest-path for data
    queue = deque(data_roots)
    for r in data_roots:
        col[r] = 0
    while queue:
        nid = queue.popleft()
        for child in data_adj.get(nid, []):
            if child not in needs:
                continue
            nc = col.get(nid, 0) + 1
            if col.get(child, -1) < nc:
                col[child] = nc
                queue.append(child)

    # Unassigned nodes
    max_col = max(col.values(), default=0)
    for nid in node_ids:
        if nid not in col:
            col[nid] = max_col + 1

    # ── Step 2: Value nodes → place in same column as first consumer ──
    # (but one column to the left if possible)
    for nid in node_ids:
        node = lnodes[nid]
        if node.data_in_count == 0 and node.data_out_count > 0 and node.ctrl_in_count == 0:
            # This is a value/source node — find first consumer
            consumers = data_adj.get(nid, [])
            if consumers:
                consumer_col = min(col.get(c, 0) for c in consumers if c in col)
                col[nid] = max(0, consumer_col - 1)

    # ── Step 3: Ctrl-connected nodes → try to be in same column ──
    # If A→B via ctrl and they're in different columns, move B to A's column
    for nid in node_ids:
        for child in ctrl_adj.get(nid, []):
            if child in needs and nid in col and child in col:
                # If they're in different columns and child has no data reason
                # to be elsewhere, move child to same column
                if col[child] != col[nid]:
                    # Only move if child's column assignment came from ctrl, not data
                    child_data_sources = data_rev.get(child, [])
                    if not child_data_sources or all(s not in needs for s in child_data_sources):
                        col[child] = col[nid]

    # ── Step 4: Group by column, order by ctrl flow within ──
    columns: dict[int, list[str]] = defaultdict(list)
    for nid in node_ids:
        columns[col[nid]].append(nid)

    for c_ids in columns.values():
        in_col = set(c_ids)
        order: dict[str, int] = {}
        idx = 0

        # Ctrl roots within this column
        c_roots = [nid for nid in c_ids
                    if not any(src in in_col for src in ctrl_rev.get(nid, []))]
        if not c_roots:
            c_roots = c_ids[:1]

        # BFS within column by ctrl edges
        vis = set()
        bfs = list(c_roots)
        for r in bfs:
            if r not in vis:
                vis.add(r)
                order[r] = idx
                idx += 1
        bi = 0
        while bi < len(bfs):
            for child in ctrl_adj.get(bfs[bi], []):
                if child in in_col and child not in vis:
                    vis.add(child)
                    order[child] = idx
                    idx += 1
                    bfs.append(child)
            bi += 1

        # Remaining unvisited — place by data dependency order
        for nid in c_ids:
            if nid not in vis:
                order[nid] = idx
                idx += 1

        c_ids.sort(key=lambda nid: order.get(nid, 999))

    # ── Step 5: Assign coordinates ──
    sorted_cols = sorted(columns.keys())
    x_off = 100
    for c in sorted_cols:
        c_ids = columns[c]
        col_w = max((lnodes[nid].width for nid in c_ids), default=MIN_WIDTH)
        y_off = 100
        for nid in c_ids:
            ln = lnodes[nid]
            ln.x = x_off
            ln.y = y_off
            ln.layer = c
            y_off += ln.height + V_SPACING
        x_off += col_w + H_SPACING

    # ── Step 6: Build output ──
    new_nodes = []
    for node in graph.nodes:
        ln = lnodes[node.id]
        new_meta = dict(node.meta)
        if not ln.has_position:
            new_meta["pos"] = [int(ln.x), int(ln.y)]
            new_meta["size"] = [int(ln.width), int(ln.height)]
        new_nodes.append(KGNode(
            id=node.id, type=node.type, name=node.name,
            data_inputs=node.data_inputs, data_outputs=node.data_outputs,
            ctrl_inputs=node.ctrl_inputs, ctrl_outputs=node.ctrl_outputs,
            properties=node.properties, meta=new_meta,
        ))

    return KirGraph(version=graph.version, nodes=new_nodes, edges=graph.edges)
