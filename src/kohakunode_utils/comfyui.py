"""Convert ComfyUI workflow JSON to KirGraph (.kirgraph) format."""

from typing import Any

from kohakunode.kirgraph.schema import KGEdge, KGNode, KGPort, KirGraph


def _normalize_pos(pos: Any) -> list[int]:
    """Normalize ComfyUI position to [x, y] list.

    Handles:
    - [x, y] arrays
    - {"0": x, "1": y} dicts (some serializers)
    - Missing/null → [0, 0]
    """
    if pos is None:
        return [0, 0]
    if isinstance(pos, dict):
        return [int(pos.get("0", 0)), int(pos.get("1", 0))]
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return [int(pos[0]), int(pos[1])]
    return [0, 0]


def _normalize_size(size: Any) -> list[int]:
    """Normalize ComfyUI size to [w, h] list."""
    if size is None:
        return [200, 100]
    if isinstance(size, dict):
        return [int(size.get("0", 200)), int(size.get("1", 100))]
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        return [int(size[0]), int(size[1])]
    return [200, 100]


def _node_id(comfy_id: int | str) -> str:
    """Convert a ComfyUI node id to a KirGraph node id."""
    return f"comfy_{comfy_id}"


def _sanitize_type(comfy_type: str) -> str:
    """Normalize a ComfyUI node type to a valid KirGraph type key.

    Lowercase, replace spaces with underscores, encode invalid chars
    as _xHH_ (hex) so the original name is recoverable.
    """
    result = []
    for ch in comfy_type.lower():
        if ch.isalnum() or ch == "_":
            result.append(ch)
        elif ch == " ":
            result.append("_")
        else:
            result.append(f"_x{ord(ch):02x}_")
    return "".join(result)


def _sanitize_port_name(name: str) -> str:
    """Sanitize a port name for use as part of a variable name.

    Lowercase, replace spaces with underscores.
    """
    return name.lower().replace(" ", "_")


def _parse_link(link: Any) -> dict[str, Any]:
    """Parse a ComfyUI link into a normalized dict.

    Handles both array format and object format:
    - Array: [link_id, origin_id, origin_slot, target_id, target_slot, type]
    - Object: {id, origin_id, origin_slot, target_id, target_slot, type}
    """
    if isinstance(link, (list, tuple)):
        return {
            "id": link[0],
            "origin_id": link[1],
            "origin_slot": link[2],
            "target_id": link[3],
            "target_slot": link[4],
            "type": link[5] if len(link) > 5 else "any",
        }
    if isinstance(link, dict):
        return {
            "id": link.get("id"),
            "origin_id": link["origin_id"],
            "origin_slot": link["origin_slot"],
            "target_id": link["target_id"],
            "target_slot": link["target_slot"],
            "type": link.get("type", "any"),
        }
    raise ValueError(f"Unsupported link format: {type(link)}")


def _is_api_format(workflow: dict) -> bool:
    """Detect ComfyUI API format (node IDs as keys, class_type fields)."""
    if "nodes" in workflow:
        return False
    for v in workflow.values():
        if isinstance(v, dict) and "class_type" in v:
            return True
    return False


# ---------------------------------------------------------------------------
# API format conversion
# ---------------------------------------------------------------------------


def _api_build_nodes(workflow: dict) -> tuple[list[KGNode], dict[str, set[str]]]:
    """First pass: build KGNodes from API-format workflow.

    Returns (kg_nodes, output_ports_seen) where output_ports_seen tracks
    which output ports are referenced by connections (filled in second pass).
    """
    kg_nodes: list[KGNode] = []
    node_ids = sorted(workflow.keys(), key=lambda k: int(k) if k.isdigit() else k)
    for i, nid in enumerate(node_ids):
        node_data = workflow[nid]
        comfy_type = node_data.get("class_type", "unknown")
        inputs_data = node_data.get("inputs", {})

        data_inputs: list[KGPort] = []
        for port_name, value in inputs_data.items():
            safe_name = _sanitize_port_name(port_name)
            if isinstance(value, list) and len(value) == 2:
                data_inputs.append(KGPort(port=safe_name, type="any"))
            else:
                data_inputs.append(KGPort(port=safe_name, type="any", default=value))

        col = i % 4
        row = i // 4
        kg_nodes.append(
            KGNode(
                id=_node_id(nid),
                type=_sanitize_type(comfy_type),
                name=comfy_type,
                data_inputs=data_inputs,
                data_outputs=[],
                ctrl_inputs=[],
                ctrl_outputs=[],
                properties={},
                meta={
                    "pos": [100 + col * 300, 100 + row * 200],
                    "size": [250, 120],
                    "comfyui_type": comfy_type,
                    "comfyui_id": nid,
                    "comfyui_api_inputs": inputs_data,
                },
            )
        )
    return kg_nodes, {}


def _api_build_edges(
    workflow: dict, node_ids: list[str]
) -> tuple[list[KGEdge], dict[str, set[str]]]:
    """Second pass: build edges and track which output ports are used."""
    kg_edges: list[KGEdge] = []
    output_ports_seen: dict[str, set[str]] = {}

    for nid in node_ids:
        inputs_data = workflow[nid].get("inputs", {})
        for port_name, value in inputs_data.items():
            if not (isinstance(value, list) and len(value) == 2):
                continue
            src_nid = str(value[0])
            src_slot = int(value[1])
            src_kg_id = _node_id(src_nid)
            dst_kg_id = _node_id(nid)
            out_port_name = f"output_{src_slot}"
            output_ports_seen.setdefault(src_kg_id, set()).add(out_port_name)
            kg_edges.append(
                KGEdge(
                    type="data",
                    from_node=src_kg_id,
                    from_port=out_port_name,
                    to_node=dst_kg_id,
                    to_port=_sanitize_port_name(port_name),
                )
            )

    return kg_edges, output_ports_seen


def _convert_api_format(workflow: dict) -> KirGraph:
    """Convert ComfyUI API format to KirGraph.

    API format: { "node_id": { "class_type": "...", "inputs": { "param": value_or_[node_id, slot] } } }
    """
    node_ids = sorted(workflow.keys(), key=lambda k: int(k) if k.isdigit() else k)
    kg_nodes, _ = _api_build_nodes(workflow)
    kg_edges, output_ports_seen = _api_build_edges(workflow, node_ids)

    node_map = {n.id: n for n in kg_nodes}
    for kg_id, port_names in output_ports_seen.items():
        node = node_map.get(kg_id)
        if node:
            for pname in sorted(port_names):
                if not any(p.port == pname for p in node.data_outputs):
                    node.data_outputs.append(KGPort(port=pname, type="any"))

    return KirGraph(version="0.1.0", nodes=kg_nodes, edges=kg_edges)


# ---------------------------------------------------------------------------
# Workflow format conversion
# ---------------------------------------------------------------------------


def _build_comfy_node(cn: dict, parsed_links: list[dict[str, Any]]) -> KGNode:
    """Convert a single ComfyUI workflow node dict to a KGNode."""
    cn_id = cn["id"]
    kg_id = _node_id(cn_id)
    comfy_type = cn.get("type", "unknown")
    kg_type = _sanitize_type(comfy_type)

    pos = _normalize_pos(cn.get("pos"))
    size = _normalize_size(cn.get("size"))

    raw_inputs = cn.get("inputs") or []
    data_inputs: list[KGPort] = [
        KGPort(
            port=_sanitize_port_name(inp.get("name", "input")),
            type=str(inp.get("type", "any")).lower(),
        )
        for inp in raw_inputs
    ]

    raw_outputs = cn.get("outputs") or []
    data_outputs: list[KGPort] = [
        KGPort(
            port=_sanitize_port_name(out.get("name", "output")),
            type=str(out.get("type", "any")).lower(),
        )
        for out in raw_outputs
    ]

    widgets = cn.get("widgets_values")
    properties: dict[str, Any] = {}
    if widgets is not None:
        properties["widgets"] = widgets
    comfy_props = cn.get("properties")
    if comfy_props:
        properties["comfyui"] = comfy_props

    if widgets:
        _apply_widget_defaults(cn_id, raw_inputs, data_inputs, widgets, parsed_links)

    meta: dict[str, Any] = {
        "pos": pos,
        "size": size,
        "comfyui_type": comfy_type,
        "comfyui_id": cn_id,
        "comfyui_inputs": raw_inputs,
        "comfyui_outputs": raw_outputs,
    }
    for key in ("mode", "order", "flags", "color", "bgcolor"):
        if key in cn:
            meta[key] = cn[key]

    return KGNode(
        id=kg_id,
        type=kg_type,
        name=comfy_type,
        data_inputs=data_inputs,
        data_outputs=data_outputs,
        ctrl_inputs=[],
        ctrl_outputs=[],
        properties=properties,
        meta=meta,
    )


def _apply_widget_defaults(
    cn_id: Any,
    raw_inputs: list,
    data_inputs: list[KGPort],
    widgets: list,
    parsed_links: list[dict[str, Any]],
) -> None:
    """Fill unconnected input slots with widget values and add extra widget ports."""
    connected_input_indices: set[int] = {
        plk["target_slot"] for plk in parsed_links if plk["target_id"] == cn_id
    }

    widget_idx = 0
    for slot_idx in range(len(raw_inputs)):
        if slot_idx in connected_input_indices:
            continue
        if widget_idx < len(widgets):
            p = data_inputs[slot_idx]
            data_inputs[slot_idx] = KGPort(
                port=p.port, type=p.type, default=widgets[widget_idx]
            )
            widget_idx += 1

    while widget_idx < len(widgets):
        data_inputs.append(
            KGPort(port=f"widget_{widget_idx}", type="any", default=widgets[widget_idx])
        )
        widget_idx += 1


def _build_port_name_lookups(
    comfy_nodes: list[dict],
) -> tuple[dict[tuple, str], dict[tuple, str]]:
    """Build (node_id, slot_index) -> port_name lookups for outputs and inputs."""
    output_port_names: dict[tuple, str] = {}
    input_port_names: dict[tuple, str] = {}
    for cn in comfy_nodes:
        cn_id = cn["id"]
        for idx, out in enumerate(cn.get("outputs") or []):
            output_port_names[(cn_id, idx)] = _sanitize_port_name(
                out.get("name", f"output_{idx}")
            )
        for idx, inp in enumerate(cn.get("inputs") or []):
            input_port_names[(cn_id, idx)] = _sanitize_port_name(
                inp.get("name", f"input_{idx}")
            )
    return output_port_names, input_port_names


def _build_edges_from_links(
    parsed_links: list[dict[str, Any]],
    output_port_names: dict[tuple, str],
    input_port_names: dict[tuple, str],
) -> list[KGEdge]:
    """Convert parsed ComfyUI links to KGEdges."""
    kg_edges: list[KGEdge] = []
    for plk in parsed_links:
        origin_id = plk["origin_id"]
        origin_slot = plk["origin_slot"]
        target_id = plk["target_id"]
        target_slot = plk["target_slot"]
        from_port = output_port_names.get(
            (origin_id, origin_slot), f"output_{origin_slot}"
        )
        to_port = input_port_names.get((target_id, target_slot), f"input_{target_slot}")
        kg_edges.append(
            KGEdge(
                type="data",
                from_node=_node_id(origin_id),
                from_port=from_port,
                to_node=_node_id(target_id),
                to_port=to_port,
            )
        )
    return kg_edges


def comfyui_to_kirgraph(workflow: dict) -> KirGraph:
    """Convert a ComfyUI workflow dict to a KirGraph.

    Supports both workflow format (nodes/links arrays) and API format
    (node IDs as keys with class_type and inputs).

    ComfyUI is pure dataflow -- all nodes get no ctrl ports.

    Args:
        workflow: Parsed ComfyUI workflow JSON dict

    Returns:
        KirGraph object
    """
    if _is_api_format(workflow):
        return _convert_api_format(workflow)

    comfy_nodes = workflow.get("nodes", [])
    comfy_links = workflow.get("links", [])
    parsed_links: list[dict[str, Any]] = [_parse_link(lk) for lk in comfy_links]

    kg_nodes = [_build_comfy_node(cn, parsed_links) for cn in comfy_nodes]
    output_port_names, input_port_names = _build_port_name_lookups(comfy_nodes)
    kg_edges = _build_edges_from_links(
        parsed_links, output_port_names, input_port_names
    )

    return KirGraph(version="0.1.0", nodes=kg_nodes, edges=kg_edges)
