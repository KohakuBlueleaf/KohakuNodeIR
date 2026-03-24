"""Convert KirGraph (.kirgraph) back to ComfyUI workflow JSON."""

from typing import Any

from kohakunode.kirgraph.schema import KGNode, KirGraph


def _build_comfy_inputs(
    node: KGNode,
    meta: dict,
    input_slot: dict[tuple[str, str], int],
) -> list[dict]:
    """Reconstruct the ComfyUI inputs array for a node, populating slot indices."""
    raw_inputs = meta.get("comfyui_inputs")
    if raw_inputs is not None:
        inputs = []
        for i, inp in enumerate(raw_inputs):
            port = (
                node.data_inputs[i].port if i < len(node.data_inputs) else f"input_{i}"
            )
            inputs.append(
                {
                    "name": inp.get("name", port),
                    "type": inp.get("type", "any").upper(),
                    "link": None,
                    "slot_index": i,
                }
            )
            input_slot[(node.id, port)] = i
    else:
        inputs = []
        for i, p in enumerate(node.data_inputs):
            inputs.append(
                {"name": p.port, "type": p.type.upper(), "link": None, "slot_index": i}
            )
            input_slot[(node.id, p.port)] = i
    return inputs


def _build_comfy_outputs(
    node: KGNode,
    meta: dict,
    output_slot: dict[tuple[str, str], int],
) -> list[dict]:
    """Reconstruct the ComfyUI outputs array for a node, populating slot indices."""
    raw_outputs = meta.get("comfyui_outputs")
    if raw_outputs is not None:
        outputs = []
        for i, out in enumerate(raw_outputs):
            port = (
                node.data_outputs[i].port
                if i < len(node.data_outputs)
                else f"output_{i}"
            )
            outputs.append(
                {
                    "name": out.get("name", port),
                    "type": out.get("type", "any").upper(),
                    "links": [],
                    "slot_index": i,
                }
            )
            output_slot[(node.id, port)] = i
    else:
        outputs = []
        for i, p in enumerate(node.data_outputs):
            outputs.append(
                {"name": p.port, "type": p.type.upper(), "links": [], "slot_index": i}
            )
            output_slot[(node.id, p.port)] = i
    return outputs


def _build_comfy_node_dict(
    node: KGNode,
    inputs: list[dict],
    outputs: list[dict],
) -> dict[str, Any]:
    """Assemble a ComfyUI node dict from a KGNode and its port lists."""
    meta = node.meta
    comfy_id = meta.get("comfyui_id", node.id.replace("comfy_", ""))
    comfy_type = meta.get("comfyui_type", node.name)
    pos = meta.get("pos", [0, 0])
    size = meta.get("size", [200, 100])

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
        "widgets_values": meta.get("widgets_values") or [],
    }
    return cn


def _convert_edges_to_links(
    graph: KirGraph,
    node_map: dict[str, dict],
    output_slot: dict[tuple[str, str], int],
    input_slot: dict[tuple[str, str], int],
) -> list[list]:
    """Convert KGEdges to ComfyUI link arrays and update node link references."""
    comfy_links: list[list] = []
    link_id_counter = 0

    for edge in graph.edges:
        if edge.type != "data":
            continue

        link_id_counter += 1
        origin_id = node_map.get(edge.from_node, {}).get("id", 0)
        target_id = node_map.get(edge.to_node, {}).get("id", 0)
        origin_s = output_slot.get((edge.from_node, edge.from_port), 0)
        target_s = input_slot.get((edge.to_node, edge.to_port), 0)

        cn_from = node_map.get(edge.from_node)
        link_type = "*"
        if cn_from and origin_s < len(cn_from["outputs"]):
            link_type = cn_from["outputs"][origin_s]["type"]

        comfy_links.append(
            [link_id_counter, origin_id, origin_s, target_id, target_s, link_type]
        )

        if cn_from and origin_s < len(cn_from["outputs"]):
            cn_from["outputs"][origin_s]["links"].append(link_id_counter)
        cn_to = node_map.get(edge.to_node)
        if cn_to and target_s < len(cn_to["inputs"]):
            cn_to["inputs"][target_s]["link"] = link_id_counter

    return comfy_links


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
    node_map: dict[str, dict] = {}
    output_slot: dict[tuple[str, str], int] = {}
    input_slot: dict[tuple[str, str], int] = {}

    for node in graph.nodes:
        inputs = _build_comfy_inputs(node, node.meta, input_slot)
        outputs = _build_comfy_outputs(node, node.meta, output_slot)
        cn = _build_comfy_node_dict(node, inputs, outputs)
        node_map[node.id] = cn
        comfy_nodes.append(cn)

    comfy_links = _convert_edges_to_links(graph, node_map, output_slot, input_slot)

    max_node_id = max(
        (cn["id"] for cn in comfy_nodes if isinstance(cn["id"], int)), default=0
    )
    state = {
        "lastNodeId": max_node_id,
        "lastLinkId": len(comfy_links),
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
