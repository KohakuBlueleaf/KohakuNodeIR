/**
 * comfyLoader.js
 * Convert a ComfyUI workflow JSON to the viewer's canonical graph format.
 *
 * Ported from src/kohakunode_utils/comfyui.py.
 *
 * Supports two ComfyUI serialisation formats:
 *
 *   Workflow format (LiteGraph JSON):
 *     { nodes: [...], links: [...], ... }
 *     Each node has: id, type, pos, size, inputs?, outputs?, widgets_values?
 *     Each link is [link_id, origin_id, origin_slot, target_id, target_slot, type]
 *     or an equivalent object.
 *
 *   API format (prompt JSON):
 *     { "node_id": { class_type: "...", inputs: { param: value_or_ref } }, ... }
 *     References are encoded as [source_node_id, output_slot].
 *
 * ComfyUI is pure dataflow — nodes get no ctrl ports.
 *
 * Viewer format returned:
 *   {
 *     nodes: [{ id, type, name, x, y, width, height,
 *               dataInputs, dataOutputs, ctrlInputs, ctrlOutputs }],
 *     edges: [{ type, fromNode, fromPort, toNode, toPort }]
 *   }
 */

// ---------------------------------------------------------------------------
// Utility helpers (mirroring the Python module)
// ---------------------------------------------------------------------------

/**
 * Normalize a ComfyUI position value to { x, y }.
 * Handles: [x, y] arrays, {"0": x, "1": y} dicts, null/undefined.
 */
function normalizePos(pos, fallbackIndex) {
  if (Array.isArray(pos) && pos.length >= 2) {
    return { x: Number(pos[0]), y: Number(pos[1]) };
  }
  if (pos && typeof pos === "object") {
    const x = pos["0"] ?? pos.x ?? 0;
    const y = pos["1"] ?? pos.y ?? 0;
    return { x: Number(x), y: Number(y) };
  }
  // Auto-layout grid (col=index%4, row=floor(index/4), spacing 300×200)
  const col = fallbackIndex % 4;
  const row = Math.floor(fallbackIndex / 4);
  return { x: 100 + col * 300, y: 100 + row * 200 };
}

/**
 * Normalize a ComfyUI size value to { width, height }.
 * Handles: [w, h] arrays, {"0": w, "1": h} dicts, null/undefined.
 */
function normalizeSize(size) {
  if (Array.isArray(size) && size.length >= 2) {
    return { width: Number(size[0]), height: Number(size[1]) };
  }
  if (size && typeof size === "object") {
    const w = size["0"] ?? size.width ?? 200;
    const h = size["1"] ?? size.height ?? 100;
    return { width: Number(w), height: Number(h) };
  }
  return { width: 200, height: 100 };
}

/**
 * Convert a ComfyUI node id to a viewer node id string.
 * Mirrors Python: f"comfy_{comfy_id}"
 */
function nodeId(comfyId) {
  return `comfy_${comfyId}`;
}

/**
 * Sanitize a ComfyUI class/node type to a safe identifier.
 * Lowercase, spaces → underscores, other non-alnum chars → _xHH_.
 * Mirrors Python: _sanitize_type()
 */
function sanitizeType(comfyType) {
  let result = "";
  for (const ch of String(comfyType).toLowerCase()) {
    if (/[a-z0-9_]/.test(ch)) {
      result += ch;
    } else if (ch === " ") {
      result += "_";
    } else {
      result += `_x${ch.charCodeAt(0).toString(16).padStart(2, "0")}_`;
    }
  }
  return result;
}

/**
 * Sanitize a port name: lowercase, spaces → underscores.
 * Mirrors Python: _sanitize_port_name()
 */
function sanitizePortName(name) {
  return String(name).toLowerCase().replace(/ /g, "_");
}

/**
 * Parse a ComfyUI link (array or object form) into a normalised object.
 * Mirrors Python: _parse_link()
 *
 * Array: [link_id, origin_id, origin_slot, target_id, target_slot, type?]
 * Object: { id, origin_id, origin_slot, target_id, target_slot, type? }
 */
function parseLink(link) {
  if (Array.isArray(link)) {
    return {
      id: link[0],
      originId: link[1],
      originSlot: link[2],
      targetId: link[3],
      targetSlot: link[4],
      type: link.length > 5 ? link[5] : "any",
    };
  }
  if (link && typeof link === "object") {
    return {
      id: link.id,
      originId: link.origin_id,
      originSlot: link.origin_slot,
      targetId: link.target_id,
      targetSlot: link.target_slot,
      type: link.type ?? "any",
    };
  }
  throw new Error(`Unsupported link format: ${typeof link}`);
}

// ---------------------------------------------------------------------------
// Format detection
// ---------------------------------------------------------------------------

/**
 * Detect whether a parsed JSON object is in ComfyUI API format.
 * Mirrors Python: _is_api_format()
 *
 * API format: keys are node IDs, values are { class_type, inputs } dicts.
 * Workflow format: top-level object has a "nodes" array.
 */
function isApiFormat(workflow) {
  if ("nodes" in workflow) return false;
  for (const v of Object.values(workflow)) {
    if (v && typeof v === "object" && "class_type" in v) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// API format converter
// ---------------------------------------------------------------------------

/**
 * Convert ComfyUI API format to the viewer graph format.
 * Mirrors Python: _convert_api_format()
 *
 * API format:
 *   { "node_id": { "class_type": "...", "inputs": { "param": value_or_[src_id, slot] } } }
 *
 * Input values:
 *   - Literal (string, number, bool, null)   → input port with default
 *   - [source_node_id, output_slot]           → connected input port → data edge
 *
 * Output ports are inferred from which slots other nodes reference.
 */
function convertApiFormat(workflow) {
  const nodes = [];
  const edges = [];

  // Stable sort: numeric IDs first in numeric order, then string IDs
  const nids = Object.keys(workflow).sort((a, b) => {
    const an = Number(a),
      bn = Number(b);
    if (!isNaN(an) && !isNaN(bn)) return an - bn;
    return String(a).localeCompare(String(b));
  });

  // First pass: create nodes
  const nodeMap = {}; // kg_id → node object

  nids.forEach((nid, i) => {
    const nodeData = workflow[nid];
    if (!nodeData || typeof nodeData !== "object") return;

    const comfyType = nodeData.class_type ?? "unknown";
    const inputsData = nodeData.inputs ?? {};

    const dataInputs = [];

    for (const [portName, value] of Object.entries(inputsData)) {
      const safeName = sanitizePortName(portName);
      if (
        Array.isArray(value) &&
        value.length === 2 &&
        (typeof value[0] === "number" || typeof value[0] === "string") &&
        typeof value[1] === "number"
      ) {
        // Connection reference [source_node_id, output_slot]
        dataInputs.push({ name: safeName, type: "any" });
      } else {
        // Literal default value
        dataInputs.push({ name: safeName, type: "any", default: value });
      }
    }

    const { x, y } = normalizePos(null, i); // API format has no position
    const kgId = nodeId(nid);

    const node = {
      id: kgId,
      type: sanitizeType(comfyType),
      name: comfyType,
      x,
      y,
      width: 250,
      height: 120,
      dataInputs,
      dataOutputs: [], // filled in during second pass
      ctrlInputs: [],
      ctrlOutputs: [],
    };

    nodes.push(node);
    nodeMap[kgId] = node;
  });

  // Second pass: create edges and infer output ports
  const outputPortsSeen = {}; // kg_id → Set of port names

  for (const nid of nids) {
    const nodeData = workflow[nid];
    if (!nodeData || typeof nodeData !== "object") continue;
    const inputsData = nodeData.inputs ?? {};

    for (const [portName, value] of Object.entries(inputsData)) {
      if (
        Array.isArray(value) &&
        value.length === 2 &&
        (typeof value[0] === "number" || typeof value[0] === "string") &&
        typeof value[1] === "number"
      ) {
        const srcNid = String(value[0]);
        const srcSlot = value[1];
        const srcKgId = nodeId(srcNid);
        const dstKgId = nodeId(nid);

        const outPortName = `output_${srcSlot}`;

        if (!outputPortsSeen[srcKgId]) outputPortsSeen[srcKgId] = new Set();
        outputPortsSeen[srcKgId].add(outPortName);

        edges.push({
          type: "data",
          fromNode: srcKgId,
          fromPort: outPortName,
          toNode: dstKgId,
          toPort: sanitizePortName(portName),
        });
      }
    }
  }

  // Add inferred output ports to nodes (sorted for determinism)
  for (const [kgId, portNames] of Object.entries(outputPortsSeen)) {
    const node = nodeMap[kgId];
    if (!node) continue;
    for (const pname of [...portNames].sort()) {
      if (!node.dataOutputs.some((p) => p.name === pname)) {
        node.dataOutputs.push({ name: pname, type: "any" });
      }
    }
  }

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Workflow format converter
// ---------------------------------------------------------------------------

/**
 * Convert ComfyUI workflow format (LiteGraph) to the viewer graph format.
 * Mirrors Python: comfyui_to_kirgraph() for workflow format.
 *
 * Workflow format:
 *   {
 *     nodes: [{ id, type, pos, size, inputs?, outputs?, widgets_values?, ... }],
 *     links: [[link_id, origin_id, origin_slot, target_id, target_slot, type], ...]
 *   }
 */
function convertWorkflowFormat(workflow) {
  const comfyNodes = workflow.nodes ?? [];
  const comfyLinks = workflow.links ?? [];

  // Parse all links up front
  const parsedLinks = comfyLinks.map(parseLink);

  // Build a per-target-node → list of links lookup (for widget_values mapping)
  const linksByTarget = {}; // comfy_node_id → Set<target_slot>
  for (const plk of parsedLinks) {
    const tid = plk.targetId;
    if (!linksByTarget[tid]) linksByTarget[tid] = new Set();
    linksByTarget[tid].add(plk.targetSlot);
  }

  // Port name lookups: (comfy_node_id, slot_index) → sanitized port name
  const outputPortNames = {}; // `${id}:${idx}` → name
  const inputPortNames = {}; // `${id}:${idx}` → name

  for (const cn of comfyNodes) {
    const cnId = cn.id;
    for (const [idx, out] of (cn.outputs ?? []).entries()) {
      outputPortNames[`${cnId}:${idx}`] = sanitizePortName(
        out.name ?? `output_${idx}`,
      );
    }
    for (const [idx, inp] of (cn.inputs ?? []).entries()) {
      inputPortNames[`${cnId}:${idx}`] = sanitizePortName(
        inp.name ?? `input_${idx}`,
      );
    }
  }

  const nodes = [];
  const edges = [];

  for (const [i, cn] of comfyNodes.entries()) {
    const cnId = cn.id;
    const kgId = nodeId(cnId);
    const comfyType = cn.type ?? "unknown";

    const { x, y } = normalizePos(cn.pos, i);
    const { width, height } = normalizeSize(cn.size);

    // Build data input ports
    const rawInputs = cn.inputs ?? [];
    const dataInputs = rawInputs.map((inp) => ({
      name: sanitizePortName(inp.name ?? "input"),
      type: String(inp.type ?? "any").toLowerCase(),
    }));

    // Build data output ports
    const rawOutputs = cn.outputs ?? [];
    const dataOutputs = rawOutputs.map((out) => ({
      name: sanitizePortName(out.name ?? "output"),
      type: String(out.type ?? "any").toLowerCase(),
    }));

    // Apply widget_values: fill in defaults for unconnected input slots,
    // then add extra widget-only ports for remaining values.
    const widgets = cn.widgets_values ?? null;
    if (widgets && widgets.length > 0) {
      const connectedSlots = linksByTarget[cnId] ?? new Set();
      let widgetIdx = 0;

      // Fill unconnected input slots first
      for (let slotIdx = 0; slotIdx < rawInputs.length; slotIdx++) {
        if (connectedSlots.has(slotIdx)) continue;
        if (widgetIdx >= widgets.length) break;
        dataInputs[slotIdx] = {
          ...dataInputs[slotIdx],
          default: widgets[widgetIdx++],
        };
      }

      // Remaining widget values become extra input ports
      while (widgetIdx < widgets.length) {
        dataInputs.push({
          name: `widget_${widgetIdx}`,
          type: "any",
          default: widgets[widgetIdx++],
        });
      }
    }

    nodes.push({
      id: kgId,
      type: sanitizeType(comfyType),
      name: comfyType,
      x,
      y,
      width,
      height,
      dataInputs,
      dataOutputs,
      ctrlInputs: [],
      ctrlOutputs: [],
    });
  }

  // Convert links to edges
  for (const plk of parsedLinks) {
    const fromPort =
      outputPortNames[`${plk.originId}:${plk.originSlot}`] ??
      `output_${plk.originSlot}`;
    const toPort =
      inputPortNames[`${plk.targetId}:${plk.targetSlot}`] ??
      `input_${plk.targetSlot}`;

    edges.push({
      type: "data",
      fromNode: nodeId(plk.originId),
      fromPort,
      toNode: nodeId(plk.targetId),
      toPort,
    });
  }

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Convert a parsed ComfyUI JSON object to the viewer graph format.
 * Automatically detects workflow vs API format.
 *
 * @param {object} json - Parsed ComfyUI JSON (workflow or API format).
 * @returns {{ nodes: object[], edges: object[] }} Viewer graph.
 */
export function loadComfyUI(json) {
  if (!json || typeof json !== "object") {
    throw new Error("loadComfyUI: expected a JSON object");
  }

  if (isApiFormat(json)) {
    return convertApiFormat(json);
  }

  return convertWorkflowFormat(json);
}
