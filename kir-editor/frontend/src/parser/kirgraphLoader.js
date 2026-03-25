/**
 * kirgraphLoader.js
 * Load a .kirgraph JSON file into the viewer's canonical graph format.
 *
 * .kirgraph format (spec: docs/kirgraph_spec.md):
 *   { version, nodes: [KGNode...], edges: [KGEdge...] }
 *
 * KGNode fields used here:
 *   id, type, name,
 *   data_inputs:  [{ port, type, default? }]
 *   data_outputs: [{ port, type }]
 *   ctrl_inputs:  [string]
 *   ctrl_outputs: [string]
 *   meta?: { pos?: [x,y], size?: [w,h] }
 *
 * KGEdge fields:
 *   type: "data" | "control"
 *   from: { node, port }
 *   to:   { node, port }
 *
 * Viewer format returned:
 *   {
 *     nodes: [{ id, type, name, x, y, width, height,
 *               dataInputs, dataOutputs, ctrlInputs, ctrlOutputs }],
 *     edges: [{ type, fromNode, fromPort, toNode, toPort }]
 *   }
 */

// Default dimensions when a node has no size metadata.
const DEFAULT_WIDTH = 180;
const DEFAULT_HEIGHT = 120;

// Auto-layout grid spacing used when no position metadata is present.
const GRID_COL_SPACING = 250;
const GRID_ROW_SPACING = 180;
const GRID_COLS = 4;

/**
 * Normalize a .kirgraph pos array/tuple to { x, y }.
 * Accepts [x, y], { "0": x, "1": y }, or null/undefined.
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
  // Auto-layout grid position
  const col = fallbackIndex % GRID_COLS;
  const row = Math.floor(fallbackIndex / GRID_COLS);
  return {
    x: 100 + col * GRID_COL_SPACING,
    y: 100 + row * GRID_ROW_SPACING,
  };
}

/**
 * Normalize a .kirgraph size array/tuple to { width, height }.
 * Accepts [w, h], { "0": w, "1": h }, or null/undefined.
 */
function normalizeSize(size) {
  if (Array.isArray(size) && size.length >= 2) {
    return { width: Number(size[0]), height: Number(size[1]) };
  }
  if (size && typeof size === "object") {
    const w = size["0"] ?? size.width ?? DEFAULT_WIDTH;
    const h = size["1"] ?? size.height ?? DEFAULT_HEIGHT;
    return { width: Number(w), height: Number(h) };
  }
  return { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT };
}

/**
 * Convert a single KGNode to the viewer node format.
 *
 * @param {object} kgNode - Raw node object from the .kirgraph JSON.
 * @param {number} index  - Node index in the list (used for auto-layout).
 * @returns {object} Viewer node.
 */
function convertNode(kgNode, index) {
  const meta = kgNode.meta ?? {};
  const { x, y } = normalizePos(meta.pos, index);
  const { width, height } = normalizeSize(meta.size);

  // data_inputs: [{ port, type, default? }]  →  dataInputs: [{ name, type, default }]
  const dataInputs = (kgNode.data_inputs ?? []).map((p) => ({
    name: p.port ?? p.name ?? "",
    type: p.type ?? "any",
    ...(p.default !== undefined ? { default: p.default } : {}),
  }));

  // data_outputs: [{ port, type }]  →  dataOutputs: [{ name, type }]
  const dataOutputs = (kgNode.data_outputs ?? []).map((p) => ({
    name: p.port ?? p.name ?? "",
    type: p.type ?? "any",
  }));

  // ctrl_inputs / ctrl_outputs are already plain string arrays.
  const ctrlInputs = (kgNode.ctrl_inputs ?? []).slice();
  const ctrlOutputs = (kgNode.ctrl_outputs ?? []).slice();

  return {
    id: String(kgNode.id),
    type: String(kgNode.type ?? "unknown"),
    name: String(kgNode.name ?? kgNode.id ?? ""),
    x,
    y,
    width,
    height,
    dataInputs,
    dataOutputs,
    ctrlInputs,
    ctrlOutputs,
  };
}

/**
 * Convert a single KGEdge to the viewer edge format.
 *
 * @param {object} kgEdge - Raw edge object from the .kirgraph JSON.
 * @returns {object} Viewer edge.
 */
function convertEdge(kgEdge) {
  return {
    type: kgEdge.type === "control" ? "control" : "data",
    fromNode: String(kgEdge.from.node),
    fromPort: String(kgEdge.from.port),
    toNode: String(kgEdge.to.node),
    toPort: String(kgEdge.to.port),
  };
}

/**
 * Load a parsed .kirgraph JSON object into the viewer graph format.
 *
 * @param {object} json - Parsed JSON (must have `nodes` and `edges` arrays).
 * @returns {{ nodes: object[], edges: object[] }} Viewer graph.
 */
export function loadKirgraph(json) {
  if (!json || typeof json !== "object") {
    throw new Error("loadKirgraph: expected a JSON object");
  }

  const rawNodes = Array.isArray(json.nodes) ? json.nodes : [];
  const rawEdges = Array.isArray(json.edges) ? json.edges : [];

  const nodes = rawNodes.map((n, i) => convertNode(n, i));
  const edges = rawEdges.map((e) => convertEdge(e));

  return { nodes, edges };
}
