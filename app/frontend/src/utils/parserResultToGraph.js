/**
 * Convert parser output (viewer-format nodes/edges) to graph store format.
 *
 * Shared by Toolbar (import), EditorCanvas (paste), and useKeyboard (paste).
 */

function makePortId(nodeId, portName, suffix) {
  const safe = portName.replace(/[^a-zA-Z0-9_]/g, '_');
  return `${nodeId}__${safe}__${suffix}`;
}

const NO_CTRL_TYPES = new Set(['value', 'load']);

/**
 * Infer a dataType from a literal default value.
 */
function inferType(value) {
  if (value === null || value === undefined) return 'any';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (typeof value === 'string') return 'str';
  return 'any';
}

/**
 * Infer a dataType for a value node from its properties.
 */
function inferValueNodeType(pn) {
  // Check if the parser gave us a properties.value
  const val = pn.properties?.value;
  if (val !== undefined && val !== null) return inferType(val);
  // Check the first data output type
  const out = pn.dataOutputs?.[0];
  if (out?.type && out.type !== 'any') return out.type;
  return 'any';
}

/**
 * @param {object[]} parserNodes  — viewer-format nodes
 * @param {object[]} parserEdges  — viewer-format edges
 * @returns {{ nodes: object[], connections: object[] }}
 */
export function parserResultToGraph(parserNodes, parserEdges) {
  const nodes = parserNodes.map((pn) => {
    const dataInputs = (pn.dataInputs ?? []).map((p) => {
      // Infer type from default value if type is 'any'
      let dataType = p.type ?? 'any';
      if (dataType === 'any' && p.default !== undefined && p.default !== null) {
        dataType = inferType(p.default);
      }
      const port = { id: makePortId(pn.id, p.name, 'di'), name: p.name, dataType };
      if (p.default !== undefined) port.defaultValue = p.default;
      return port;
    });

    const dataOutputs = (pn.dataOutputs ?? []).map((p) => ({
      id: makePortId(pn.id, p.name, 'do'),
      name: p.name,
      dataType: p.type ?? 'any',
    }));

    let rawCtrlIn = pn.ctrlInputs ?? [];
    let rawCtrlOut = pn.ctrlOutputs ?? [];
    if (!NO_CTRL_TYPES.has(pn.type) && rawCtrlIn.length === 0 && rawCtrlOut.length === 0) {
      rawCtrlIn = ['in'];
      rawCtrlOut = ['out'];
    }

    const ctrlInputs = rawCtrlIn.map((name) => ({ id: makePortId(pn.id, name, 'ci'), name }));
    const ctrlOutputs = rawCtrlOut.map((name) => ({ id: makePortId(pn.id, name, 'co'), name }));

    // Build properties — preserve value node data
    const properties = {};
    if (pn.type === 'value') {
      const val = pn.properties?.value;
      properties.value = val ?? null;
      properties.valueType = inferValueNodeType(pn);
    }

    return {
      id: pn.id,
      type: pn.type ?? 'function',
      name: pn.name ?? pn.type ?? 'Node',
      x: pn.x ?? 0,
      y: pn.y ?? 0,
      width: pn.width ?? 160,
      height: pn.height ?? 120,
      dataPorts: { inputs: dataInputs, outputs: dataOutputs },
      controlPorts: { inputs: ctrlInputs, outputs: ctrlOutputs },
      properties,
    };
  });

  const portIdLookup = new Map();
  for (const node of nodes) {
    for (const p of node.dataPorts.inputs) portIdLookup.set(`${node.id}|${p.name}|di`, p.id);
    for (const p of node.dataPorts.outputs) portIdLookup.set(`${node.id}|${p.name}|do`, p.id);
    for (const p of node.controlPorts.inputs) portIdLookup.set(`${node.id}|${p.name}|ci`, p.id);
    for (const p of node.controlPorts.outputs) portIdLookup.set(`${node.id}|${p.name}|co`, p.id);
  }

  const connections = (parserEdges ?? []).map((edge, i) => {
    const isCtrl = edge.type === 'control';
    const fromSuffix = isCtrl ? 'co' : 'do';
    const toSuffix = isCtrl ? 'ci' : 'di';
    const fromPortId =
      portIdLookup.get(`${edge.fromNode}|${edge.fromPort}|${fromSuffix}`) ??
      makePortId(edge.fromNode, edge.fromPort, fromSuffix);
    const toPortId =
      portIdLookup.get(`${edge.toNode}|${edge.toPort}|${toSuffix}`) ??
      makePortId(edge.toNode, edge.toPort, toSuffix);
    return {
      _edgeIndex: i,
      fromNodeId: edge.fromNode,
      fromPortId,
      toNodeId: edge.toNode,
      toPortId,
      portType: isCtrl ? 'control' : 'data',
    };
  });

  return { nodes, connections };
}
