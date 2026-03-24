"""Convert KirGraph (.kirgraph) back to ComfyUI workflow JSON."""

from __future__ import annotations

from typing import Any

from kohakunode.kirgraph.schema import KirGraph


def kirgraph_to_comfyui(graph: KirGraph) -> dict:
    """Convert a KirGraph back to ComfyUI workflow JSON.

    Uses meta fields (comfyui_type, comfyui_id, comfyui_inputs,
    comfyui_outputs, widgets_values) stored during import to
    reconstruct the original ComfyUI format.

    Args:
        graph: KirGraph object (typically from comfyui_to_kirgraph)

    Returns:
        ComfyUI workflow dict with nodes, links, groups, state, extra
    """
    comfy_nodes: list[dict] = []
    comfy_links: list[list] = []

    # Build node lookup and port→slot mappings
    node_map: dict[str, dict] = {}
    # Map (kg_node_id, port_name) → slot_index for outputs and inputs
    output_slot: dict[tuple[str, str], int] = {}
    input_slot: dict[tuple[str, str], int] = {}

    link_id_counter = 0

    for node in graph.nodes:
        meta = node.meta
        comfy_id = meta.get("comfyui_id", node.id.replace("comfy_", ""))
        comfy_type = meta.get("comfyui_type", node.name)
        pos = meta.get("pos", [0, 0])
        size = meta.get("size", [200, 100])

        # Reconstruct inputs from meta or from data_inputs
        raw_inputs = meta.get("comfyui_inputs")
        if raw_inputs is not None:
            inputs = []
            for i, inp in enumerate(raw_inputs):
                inputs.append({
                    "name": inp.get("name", node.data_inputs[i].port if i < len(node.data_inputs) else f"input_{i}"),
                    "type": inp.get("type", "any").upper(),
                    "link": None,  # filled in below
                    "slot_index": i,
                })
                input_slot[(node.id, node.data_inputs[i].port if i < len(node.data_inputs) else f"input_{i}")] = i
        else:
            inputs = []
            for i, p in enumerate(node.data_inputs):
                inputs.append({"name": p.port, "type": p.type.upper(), "link": None, "slot_index": i})
                input_slot[(node.id, p.port)] = i

        # Reconstruct outputs from meta or from data_outputs
        raw_outputs = meta.get("comfyui_outputs")
        if raw_outputs is not None:
            outputs = []
            for i, out in enumerate(raw_outputs):
                outputs.append({
                    "name": out.get("name", node.data_outputs[i].port if i < len(node.data_outputs) else f"output_{i}"),
                    "type": out.get("type", "any").upper(),
                    "links": [],
                    "slot_index": i,
                })
                output_slot[(node.id, node.data_outputs[i].port if i < len(node.data_outputs) else f"output_{i}")] = i
        else:
            outputs = []
            for i, p in enumerate(node.data_outputs):
                outputs.append({"name": p.port, "type": p.type.upper(), "links": [], "slot_index": i})
                output_slot[(node.id, p.port)] = i

        cn: dict[str, Any] = {
            "id": int(comfy_id) if str(comfy_id).isdigit() else comfy_id,
            "type": comfy_type,
            "pos": list(pos),
            "size": list(size),
            "flags": meta.get("flags", {}),
            "order": meta.get("order", 0),
            "mode": meta.get("mode", 0),
            "inputs": inputs,
            "outputs": outputs,
            "properties": {"Node name for S&R": comfy_type},
        }
        widgets = meta.get("widgets_values")
        if widgets is not None:
            cn["widgets_values"] = widgets
        else:
            cn["widgets_values"] = []

        node_map[node.id] = cn
        comfy_nodes.append(cn)

    # Convert edges to links
    for edge in graph.edges:
        if edge.type != "data":
            continue

        link_id_counter += 1
        origin_id = node_map.get(edge.from_node, {}).get("id", 0)
        target_id = node_map.get(edge.to_node, {}).get("id", 0)
        origin_s = output_slot.get((edge.from_node, edge.from_port), 0)
        target_s = input_slot.get((edge.to_node, edge.to_port), 0)

        # Determine type string from output port
        cn_from = node_map.get(edge.from_node)
        link_type = "*"
        if cn_from and origin_s < len(cn_from["outputs"]):
            link_type = cn_from["outputs"][origin_s]["type"]

        comfy_links.append([link_id_counter, origin_id, origin_s, target_id, target_s, link_type])

        # Update link references on nodes
        if cn_from and origin_s < len(cn_from["outputs"]):
            cn_from["outputs"][origin_s]["links"].append(link_id_counter)
        cn_to = node_map.get(edge.to_node)
        if cn_to and target_s < len(cn_to["inputs"]):
            cn_to["inputs"][target_s]["link"] = link_id_counter

    # Build state
    max_node_id = max((cn["id"] for cn in comfy_nodes if isinstance(cn["id"], int)), default=0)
    state = {
        "lastNodeId": max_node_id,
        "lastLinkId": link_id_counter,
        "lastGroupId": 0,
        "lastRerouteId": 0,
    }

    return {
        "version": 1,
        "nodes": comfy_nodes,
        "links": comfy_links,
        "groups": [],
        "state": state,
        "extra": {},
    }
