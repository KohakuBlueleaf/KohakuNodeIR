"""Convert ComfyUI workflow JSON to KirGraph (.kirgraph) format."""

from __future__ import annotations

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

    Lowercase, replace spaces with underscores.
    """
    return comfy_type.lower().replace(" ", "_")


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


def comfyui_to_kirgraph(workflow: dict) -> KirGraph:
    """Convert a ComfyUI workflow dict to a KirGraph.

    ComfyUI is pure dataflow -- all nodes get no ctrl ports.
    Each ComfyUI node becomes a KGNode with data ports only.
    Each ComfyUI link becomes a KGEdge of type "data".

    Args:
        workflow: Parsed ComfyUI workflow JSON dict

    Returns:
        KirGraph object
    """
    comfy_nodes = workflow.get("nodes", [])
    comfy_links = workflow.get("links", [])

    # Build a lookup: comfy_node_id -> node dict
    node_map: dict[int | str, dict] = {}
    for cn in comfy_nodes:
        node_map[cn["id"]] = cn

    # Build a lookup: link_id -> parsed link
    parsed_links: list[dict[str, Any]] = [_parse_link(lk) for lk in comfy_links]

    # Build output port lookup: (node_id, slot_index) -> port info
    # and input port lookup: (node_id, slot_index) -> port info
    # These are needed to resolve slot indices to port names.

    kg_nodes: list[KGNode] = []
    kg_edges: list[KGEdge] = []

    for cn in comfy_nodes:
        cn_id = cn["id"]
        kg_id = _node_id(cn_id)
        comfy_type = cn.get("type", "unknown")
        kg_type = _sanitize_type(comfy_type)

        # Position and size
        pos = _normalize_pos(cn.get("pos"))
        size = _normalize_size(cn.get("size"))

        # Data inputs
        raw_inputs = cn.get("inputs") or []
        data_inputs: list[KGPort] = []
        for inp in raw_inputs:
            port_name = _sanitize_port_name(inp.get("name", "input"))
            port_type = str(inp.get("type", "any")).lower()
            data_inputs.append(KGPort(port=port_name, type=port_type))

        # Data outputs
        raw_outputs = cn.get("outputs") or []
        data_outputs: list[KGPort] = []
        for out in raw_outputs:
            port_name = _sanitize_port_name(out.get("name", "output"))
            port_type = str(out.get("type", "any")).lower()
            data_outputs.append(KGPort(port=port_name, type=port_type))

        # Widget values -> properties
        widgets = cn.get("widgets_values")
        properties: dict[str, Any] = {}
        if widgets is not None:
            properties["widgets"] = widgets
        # Preserve original ComfyUI properties too
        comfy_props = cn.get("properties")
        if comfy_props:
            properties["comfyui"] = comfy_props

        # Assign widget values as defaults to unconnected input ports.
        # ComfyUI convention: widgets_values fills inputs that are NOT connected
        # in the order they appear. Connected inputs are skipped.
        if widgets:
            connected_input_indices: set[int] = set()
            for plk in parsed_links:
                if plk["target_id"] == cn_id:
                    connected_input_indices.add(plk["target_slot"])

            widget_idx = 0
            for slot_idx, inp in enumerate(raw_inputs):
                if slot_idx in connected_input_indices:
                    continue
                # This input is unconnected, assign widget default
                if widget_idx < len(widgets):
                    data_inputs[slot_idx] = KGPort(
                        port=data_inputs[slot_idx].port,
                        type=data_inputs[slot_idx].type,
                        default=widgets[widget_idx],
                    )
                    widget_idx += 1

        meta: dict[str, Any] = {"pos": pos, "size": size}
        # Preserve mode and order for round-tripping
        if "mode" in cn:
            meta["mode"] = cn["mode"]
        if "order" in cn:
            meta["order"] = cn["order"]

        kg_nodes.append(
            KGNode(
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
        )

    # Build port name lookups for edge resolution
    # (comfy_node_id, slot_index) -> port_name
    output_port_names: dict[tuple[int | str, int], str] = {}
    input_port_names: dict[tuple[int | str, int], str] = {}

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

    # Convert links to edges
    for plk in parsed_links:
        origin_id = plk["origin_id"]
        origin_slot = plk["origin_slot"]
        target_id = plk["target_id"]
        target_slot = plk["target_slot"]

        # Resolve port names
        from_port = output_port_names.get(
            (origin_id, origin_slot), f"output_{origin_slot}"
        )
        to_port = input_port_names.get(
            (target_id, target_slot), f"input_{target_slot}"
        )

        kg_edges.append(
            KGEdge(
                type="data",
                from_node=_node_id(origin_id),
                from_port=from_port,
                to_node=_node_id(target_id),
                to_port=to_port,
            )
        )

    return KirGraph(version="0.1.0", nodes=kg_nodes, edges=kg_edges)
