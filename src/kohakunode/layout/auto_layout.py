"""Auto-layout for KirGraph nodes — EDA-inspired placement algorithm.

Assigns positions and sizes to nodes that lack @meta position info,
using a modified Sugiyama layered graph layout:

1. SIZE ESTIMATION — infer node dimensions from port counts
2. LAYER ASSIGNMENT — BFS/toposort depth from roots
3. ORDERING — barycenter heuristic to minimize edge crossings
4. COORDINATE ASSIGNMENT — place nodes with proper spacing
5. OVERLAP RESOLUTION — push apart any overlapping nodes

Supports both control-flow-primary (Fischer-style: vertical=ctrl,
horizontal=data) and data-flow-primary (left-to-right) layouts.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field

from kohakunode.kirgraph.schema import KGNode, KirGraph

# Layout constants matching BaseNode.vue
CTRL_ROW_H = 18
HEADER_H = 32
DATA_ROW_H = 28
MIN_WIDTH = 180
MIN_HEIGHT = 100
H_SPACING = 60  # horizontal gap between nodes
V_SPACING = 40  # vertical gap between nodes


@dataclass
class LayoutNode:
    """Internal node representation for layout computation."""

    id: str
    width: float = 0.0
    height: float = 0.0
    x: float = 0.0
    y: float = 0.0
    layer: int = -1
    order: int = 0  # position within layer
    has_position: bool = False  # True if @meta pos was provided

    # Port counts for size estimation
    data_in_count: int = 0
    data_out_count: int = 0
    ctrl_in_count: int = 0
    ctrl_out_count: int = 0


def estimate_node_size(node: KGNode) -> tuple[float, float]:
    """Estimate node width and height from port counts."""
    n_data_in = len(node.data_inputs)
    n_data_out = len(node.data_outputs)
    n_ctrl_in = len(node.ctrl_inputs)
    n_ctrl_out = len(node.ctrl_outputs)

    data_rows = max(n_data_in, n_data_out)
    width = max(
        MIN_WIDTH,
        max(n_ctrl_in, n_ctrl_out) * 60 + 60,
    )
    height = max(
        MIN_HEIGHT,
        (CTRL_ROW_H if n_ctrl_in > 0 else 0)
        + HEADER_H
        + data_rows * DATA_ROW_H
        + (CTRL_ROW_H if n_ctrl_out > 0 else 0)
        + 16,
    )
    return (width, height)


def auto_layout(graph: KirGraph) -> KirGraph:
    """Assign positions to nodes without @meta position info.

    Nodes that already have positions are kept in place. Only nodes
    with missing or (0, 0) positions are repositioned.

    Returns a new KirGraph with updated node positions.
    """
    # Build layout nodes
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

        ln = LayoutNode(
            id=node.id,
            width=w,
            height=h,
            x=pos[0] if has_pos else 0,
            y=pos[1] if has_pos else 0,
            has_position=has_pos,
            data_in_count=len(node.data_inputs),
            data_out_count=len(node.data_outputs),
            ctrl_in_count=len(node.ctrl_inputs),
            ctrl_out_count=len(node.ctrl_outputs),
        )
        lnodes[node.id] = ln

    # If all nodes have positions, nothing to do
    needs_layout = [ln for ln in lnodes.values() if not ln.has_position]
    if not needs_layout:
        return graph

    # Build adjacency from edges
    ctrl_adj: dict[str, list[str]] = defaultdict(list)  # from → [to]
    ctrl_rev: dict[str, list[str]] = defaultdict(list)  # to → [from]
    data_adj: dict[str, list[str]] = defaultdict(list)
    data_rev: dict[str, list[str]] = defaultdict(list)

    for edge in graph.edges:
        if edge.type == "control":
            ctrl_adj[edge.from_node].append(edge.to_node)
            ctrl_rev[edge.to_node].append(edge.from_node)
        else:
            data_adj[edge.from_node].append(edge.to_node)
            data_rev[edge.to_node].append(edge.from_node)

    # Determine layout mode
    has_ctrl = any(e.type == "control" for e in graph.edges)

    if has_ctrl:
        _layout_controlflow(lnodes, ctrl_adj, ctrl_rev, data_adj, data_rev)
    else:
        _layout_dataflow(lnodes, data_adj, data_rev)

    # Build output graph with updated positions
    new_nodes: list[KGNode] = []
    for node in graph.nodes:
        ln = lnodes[node.id]
        new_meta = dict(node.meta)
        if not ln.has_position:
            new_meta["pos"] = [int(ln.x), int(ln.y)]
            new_meta["size"] = [int(ln.width), int(ln.height)]
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


# ---------------------------------------------------------------------------
# Control-flow layout (Fischer-style: vertical=ctrl, horizontal=data)
# ---------------------------------------------------------------------------


def _layout_controlflow(
    lnodes: dict[str, LayoutNode],
    ctrl_adj: dict[str, list[str]],
    ctrl_rev: dict[str, list[str]],
    data_adj: dict[str, list[str]],
    data_rev: dict[str, list[str]],
) -> None:
    """Place nodes with control flow as primary vertical axis."""
    needs = {nid: ln for nid, ln in lnodes.items() if not ln.has_position}
    if not needs:
        return

    # Combined adjacency for layer assignment
    all_adj = defaultdict(list)
    all_rev = defaultdict(list)
    for src, dsts in ctrl_adj.items():
        all_adj[src].extend(dsts)
    for dst, srcs in ctrl_rev.items():
        all_rev[dst].extend(srcs)
    for src, dsts in data_adj.items():
        all_adj[src].extend(dsts)
    for dst, srcs in data_rev.items():
        all_rev[dst].extend(srcs)

    _assign_layers(needs, all_adj, all_rev)
    _order_within_layers(needs, all_adj, all_rev)
    _assign_coordinates(needs)
    _resolve_overlaps(needs, lnodes)


# ---------------------------------------------------------------------------
# Data-flow layout (left-to-right)
# ---------------------------------------------------------------------------


def _layout_dataflow(
    lnodes: dict[str, LayoutNode],
    data_adj: dict[str, list[str]],
    data_rev: dict[str, list[str]],
) -> None:
    """Place nodes with data flow as primary horizontal axis."""
    needs = {nid: ln for nid, ln in lnodes.items() if not ln.has_position}
    if not needs:
        return

    _assign_layers(needs, data_adj, data_rev)
    _order_within_layers(needs, data_adj, data_rev)
    _assign_coordinates(needs)
    _resolve_overlaps(needs, lnodes)


# ---------------------------------------------------------------------------
# Shared layout steps
# ---------------------------------------------------------------------------


def _assign_layers(
    nodes: dict[str, LayoutNode],
    adj: dict[str, list[str]],
    rev: dict[str, list[str]],
) -> None:
    """Assign layer (depth) to each node via BFS from roots."""
    # Find roots: nodes with no incoming edges (within the set to layout)
    node_ids = set(nodes.keys())
    roots = [nid for nid in node_ids if not any(s in node_ids for s in rev.get(nid, []))]
    if not roots:
        roots = list(node_ids)[:1]

    # BFS layer assignment
    queue: deque[str] = deque()
    for r in roots:
        nodes[r].layer = 0
        queue.append(r)

    while queue:
        nid = queue.popleft()
        current_layer = nodes[nid].layer
        for child in adj.get(nid, []):
            if child not in nodes:
                continue
            new_layer = current_layer + 1
            if nodes[child].layer < new_layer:
                nodes[child].layer = new_layer
                queue.append(child)

    # Assign remaining (cycles) to max_layer + 1
    max_layer = max((ln.layer for ln in nodes.values() if ln.layer >= 0), default=0)
    for ln in nodes.values():
        if ln.layer < 0:
            ln.layer = max_layer + 1


def _order_within_layers(
    nodes: dict[str, LayoutNode],
    adj: dict[str, list[str]],
    rev: dict[str, list[str]],
) -> None:
    """Order nodes within each layer using barycenter heuristic."""
    # Group by layer
    layers: dict[int, list[str]] = defaultdict(list)
    for nid, ln in nodes.items():
        layers[ln.layer].append(nid)

    # Initial order by id (deterministic)
    for layer_ids in layers.values():
        layer_ids.sort()
        for i, nid in enumerate(layer_ids):
            nodes[nid].order = i

    # Barycenter sweep (2 passes: forward then backward)
    sorted_layers = sorted(layers.keys())
    for _ in range(3):  # iterate for convergence
        # Forward sweep
        for li in range(1, len(sorted_layers)):
            layer = sorted_layers[li]
            _barycenter_sort(layers[layer], nodes, rev, nodes)
        # Backward sweep
        for li in range(len(sorted_layers) - 2, -1, -1):
            layer = sorted_layers[li]
            _barycenter_sort(layers[layer], nodes, adj, nodes)


def _barycenter_sort(
    layer_ids: list[str],
    nodes: dict[str, LayoutNode],
    neighbor_map: dict[str, list[str]],
    all_nodes: dict[str, LayoutNode],
) -> None:
    """Sort nodes in a layer by barycenter of their neighbors."""

    def bary(nid: str) -> float:
        neighbors = [
            n for n in neighbor_map.get(nid, []) if n in all_nodes
        ]
        if not neighbors:
            return nodes[nid].order
        return sum(all_nodes[n].order for n in neighbors) / len(neighbors)

    layer_ids.sort(key=bary)
    for i, nid in enumerate(layer_ids):
        nodes[nid].order = i


def _assign_coordinates(nodes: dict[str, LayoutNode]) -> None:
    """Convert layer + order to x, y coordinates."""
    # Group by layer
    layers: dict[int, list[str]] = defaultdict(list)
    for nid, ln in nodes.items():
        layers[ln.layer].append(nid)

    for layer_ids in layers.values():
        layer_ids.sort(key=lambda nid: nodes[nid].order)

    # Assign x per layer, y per order within layer
    x_offset = 100
    for layer_idx in sorted(layers.keys()):
        layer_ids = layers[layer_idx]

        # Find max width in this layer for column spacing
        max_width = max((nodes[nid].width for nid in layer_ids), default=MIN_WIDTH)

        y_offset = 100
        for nid in layer_ids:
            ln = nodes[nid]
            ln.x = x_offset
            ln.y = y_offset
            y_offset += ln.height + V_SPACING

        x_offset += max_width + H_SPACING


def _resolve_overlaps(
    placed: dict[str, LayoutNode],
    all_nodes: dict[str, LayoutNode],
) -> None:
    """Push apart any overlapping nodes."""
    # Check against ALL nodes (including pre-positioned ones)
    fixed = [ln for ln in all_nodes.values() if ln.has_position]

    for ln in placed.values():
        for other in fixed:
            if ln.id == other.id:
                continue
            if _overlaps(ln, other):
                # Push the placed node down
                ln.y = other.y + other.height + V_SPACING

        # Check against other placed nodes
        for other in placed.values():
            if ln.id >= other.id:
                continue
            if _overlaps(ln, other):
                other.y = ln.y + ln.height + V_SPACING


def _overlaps(a: LayoutNode, b: LayoutNode) -> bool:
    """Check if two nodes overlap (with margin)."""
    margin = 10
    return (
        a.x < b.x + b.width + margin
        and a.x + a.width + margin > b.x
        and a.y < b.y + b.height + margin
        and a.y + a.height + margin > b.y
    )
