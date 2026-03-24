import { computed } from 'vue';

// ---- Constants ----
// Node types that have control flow (ctrl inputs + outputs)
const CONTROL_FLOW_TYPES = new Set(['branch', 'merge', 'switch', 'parallel']);
// Node types that are purely data (no ctrl ports by nature)
const DATA_ONLY_TYPES = new Set(['value', 'load']);
// Node types that are C-block shaped (wrap arms)
const C_BLOCK_TYPES = new Set(['branch', 'switch', 'parallel']);
// Loop-like types (single-body wrap)
const LOOP_TYPES = new Set([]); // reserved for future loop node

/**
 * Determine block render type from a graph node.
 * @param {object} node
 * @returns {'hat'|'statement'|'branch'|'switch'|'parallel'|'loop'|'value'|'reporter'}
 */
function blockTypeOf(node) {
  if (C_BLOCK_TYPES.has(node.type)) return node.type; // 'branch'|'switch'|'parallel'
  if (LOOP_TYPES.has(node.type)) return 'loop';
  if (DATA_ONLY_TYPES.has(node.type)) return 'value';
  // Nodes with ctrl ports but no ctrl inputs = chain roots → hat blocks
  const hasCtrlIn = node.controlPorts.inputs.length > 0;
  const hasCtrlOut = node.controlPorts.outputs.length > 0;
  if (!hasCtrlIn && hasCtrlOut) return 'hat';
  if (!hasCtrlIn && !hasCtrlOut) return 'reporter'; // pure data
  return 'statement';
}

/**
 * Build a lookup map: portId → connection (for fast traversal).
 * @param {object[]} connectionList
 * @returns {{ byFromPort: Map, byToPort: Map }}
 */
function buildConnectionIndex(connectionList) {
  const byFromPort = new Map(); // fromPortId → conn
  const byToPort = new Map();   // toPortId → conn
  for (const conn of connectionList) {
    byFromPort.set(conn.fromPortId, conn);
    byToPort.set(conn.toPortId, conn);
  }
  return { byFromPort, byToPort };
}

/**
 * Find all control chain roots: nodes that have ctrl output(s) but no ctrl input
 * connected to any other node's ctrl output.
 *
 * A node is a root if none of its ctrl input ports has an incoming ctrl connection.
 *
 * @param {object[]} nodeList
 * @param {{ byToPort: Map }} idx
 * @returns {object[]}
 */
function findCtrlRoots(nodeList, idx) {
  return nodeList.filter((node) => {
    const hasCtrlOut = node.controlPorts.outputs.length > 0;
    if (!hasCtrlOut) return false;
    // Has no incoming ctrl connection on any ctrl input port
    const hasIncomingCtrl = node.controlPorts.inputs.some((p) => idx.byToPort.has(p.id));
    return !hasIncomingCtrl;
  });
}

/**
 * Given a node and its ctrl output port, follow the ctrl chain and collect the
 * sequence of Block objects. Stops when there is no further ctrl connection or
 * when we hit a merge node.
 *
 * @param {string} startNodeId      - node to start from
 * @param {string|null} startPortId - ctrl output port to follow (null = first output)
 * @param {Map} nodesMap
 * @param {object} idx
 * @param {Set} visited             - guard against cycles
 * @returns {Block[]}
 */
function walkCtrlChain(startNodeId, startPortId, nodesMap, idx, visited) {
  const blocks = [];
  let currentId = startNodeId;
  let currentPortId = startPortId;

  while (currentId) {
    if (visited.has(currentId)) break;
    visited.add(currentId);

    const node = nodesMap.get(currentId);
    if (!node) break;

    const block = buildBlock(node, nodesMap, idx, visited);
    blocks.push(block);

    // Find the "main" (first or only) ctrl output to follow
    const ctrlOuts = node.controlPorts.outputs;
    if (ctrlOuts.length === 0) break;

    // For C-blocks (branch/switch/parallel) the arms were already recursed;
    // there is no single "next" output to follow linearly—arms diverge.
    // We stop the chain here; arms are embedded inside the block.
    if (C_BLOCK_TYPES.has(node.type) || LOOP_TYPES.has(node.type)) break;

    // For merge nodes we also stop (they are targets, not sources)
    if (node.type === 'merge') break;

    // Follow first ctrl output
    const outPort = currentPortId
      ? ctrlOuts.find((p) => p.id === currentPortId) ?? ctrlOuts[0]
      : ctrlOuts[0];
    const conn = idx.byFromPort.get(outPort.id);
    if (!conn || conn.portType !== 'control') break;

    currentId = conn.toNodeId;
    currentPortId = null; // reset—follow first output of next node
  }

  return blocks;
}

/**
 * Resolve inline data inputs for a node:
 * For each data input port, find what's connected or fall back to defaultValue.
 *
 * @param {object} node
 * @param {Map} nodesMap
 * @param {object} idx
 * @returns {InputSlot[]}
 */
function resolveInputSlots(node, nodesMap, idx) {
  return node.dataPorts.inputs.map((port) => {
    const conn = idx.byToPort.get(port.id);
    if (conn && conn.portType === 'data') {
      const srcNode = nodesMap.get(conn.fromNodeId);
      if (srcNode) {
        return {
          portId: port.id,
          portName: port.name,
          dataType: port.dataType ?? 'any',
          connected: true,
          sourceNodeId: conn.fromNodeId,
          sourcePortId: conn.fromPortId,
          sourceNodeType: srcNode.type,
          sourceNodeName: srcNode.name,
          // Inline literal value if the source is a value node
          literalValue:
            DATA_ONLY_TYPES.has(srcNode.type)
              ? (srcNode.properties?.value ?? srcNode.dataPorts.outputs[0]?.defaultValue ?? null)
              : null,
        };
      }
    }
    return {
      portId: port.id,
      portName: port.name,
      dataType: port.dataType ?? 'any',
      connected: false,
      sourceNodeId: null,
      sourcePortId: null,
      sourceNodeType: null,
      sourceNodeName: null,
      literalValue: port.defaultValue ?? null,
    };
  });
}

/**
 * Resolve output labels for a node's data output ports.
 * @param {object} node
 * @returns {string[]}
 */
function resolveOutputLabels(node) {
  return node.dataPorts.outputs.map((p) => p.name);
}

/**
 * Build a single Block object for a node, recursing into arms for C-blocks.
 *
 * @param {object} node
 * @param {Map} nodesMap
 * @param {object} idx
 * @param {Set} visited
 * @returns {Block}
 */
function buildBlock(node, nodesMap, idx, visited) {
  const type = blockTypeOf(node);
  const inputs = resolveInputSlots(node, nodesMap, idx);
  const outputs = resolveOutputLabels(node);

  const block = {
    nodeId: node.id,
    type,
    node,
    inputs,
    outputs,
  };

  // Recurse into arms for C-blocks
  if (node.type === 'branch') {
    // Two arms: true / false
    const truePort = node.controlPorts.outputs.find((p) => p.name === 'true') ?? node.controlPorts.outputs[0];
    const falsePort = node.controlPorts.outputs.find((p) => p.name === 'false') ?? node.controlPorts.outputs[1];

    block.arms = [
      {
        label: 'true',
        portId: truePort?.id ?? null,
        blocks: truePort ? walkArmChain(truePort.id, nodesMap, idx, new Set(visited)) : [],
      },
      {
        label: 'false',
        portId: falsePort?.id ?? null,
        blocks: falsePort ? walkArmChain(falsePort.id, nodesMap, idx, new Set(visited)) : [],
      },
    ];
  } else if (node.type === 'switch') {
    // N arms, one per ctrl output
    block.arms = node.controlPorts.outputs.map((port) => ({
      label: port.name,
      portId: port.id,
      blocks: walkArmChain(port.id, nodesMap, idx, new Set(visited)),
    }));
  } else if (node.type === 'parallel') {
    // N arms, one per ctrl output
    block.arms = node.controlPorts.outputs.map((port) => ({
      label: port.name,
      portId: port.id,
      blocks: walkArmChain(port.id, nodesMap, idx, new Set(visited)),
    }));
  } else if (LOOP_TYPES.has(node.type)) {
    // Loop body: follow the first ctrl output
    const bodyPort = node.controlPorts.outputs[0];
    block.body = bodyPort ? walkArmChain(bodyPort.id, nodesMap, idx, new Set(visited)) : [];
  }

  return block;
}

/**
 * Walk a ctrl arm starting from a given ctrl OUTPUT port id.
 * Finds the connection leaving that port, then walks the chain.
 *
 * @param {string} fromPortId
 * @param {Map} nodesMap
 * @param {object} idx
 * @param {Set} visited
 * @returns {Block[]}
 */
function walkArmChain(fromPortId, nodesMap, idx, visited) {
  const conn = idx.byFromPort.get(fromPortId);
  if (!conn || conn.portType !== 'control') return [];
  return walkCtrlChain(conn.toNodeId, null, nodesMap, idx, visited);
}

/**
 * Build block stacks for all purely-data nodes (no ctrl ports at all).
 * These become standalone reporter stacks.
 *
 * @param {object[]} nodeList
 * @param {Set} visitedNodeIds  - nodes already placed in ctrl chains
 * @param {Map} nodesMap
 * @param {object} idx
 * @returns {BlockStack[]}
 */
function buildDataStacks(nodeList, visitedNodeIds, nodesMap, idx) {
  const stacks = [];
  for (const node of nodeList) {
    if (visitedNodeIds.has(node.id)) continue;
    if (node.controlPorts.inputs.length === 0 && node.controlPorts.outputs.length === 0) {
      const block = buildBlock(node, nodesMap, idx, new Set());
      stacks.push({ rootNodeId: node.id, blocks: [block], isDataOnly: true });
      visitedNodeIds.add(node.id);
    }
  }
  return stacks;
}

/**
 * Build block stacks for nodes that have ctrl ports but were not reachable
 * from any root (disconnected mid-chain fragments).
 *
 * @param {object[]} nodeList
 * @param {Set} visitedNodeIds
 * @param {Map} nodesMap
 * @param {object} idx
 * @returns {BlockStack[]}
 */
function buildOrphanStacks(nodeList, visitedNodeIds, nodesMap, idx) {
  const stacks = [];
  for (const node of nodeList) {
    if (visitedNodeIds.has(node.id)) continue;
    const block = buildBlock(node, nodesMap, idx, new Set([node.id]));
    stacks.push({ rootNodeId: node.id, blocks: [block], isOrphan: true });
    visitedNodeIds.add(node.id);
  }
  return stacks;
}

// ---- Public composable ----

/**
 * Reactive composable that derives a block tree from the graph store.
 *
 * @param {import('pinia').Store} graphStore
 * @returns {{ blockTree: import('vue').ComputedRef }}
 */
export function useBlockTree(graphStore) {
  const blockTree = computed(() => {
    const nodeList = graphStore.nodeList;
    const connectionList = graphStore.connectionList;

    if (!nodeList.length) {
      return { stacks: [] };
    }

    // Build fast-lookup index
    const idx = buildConnectionIndex(connectionList);

    // Build node map for O(1) lookups
    const nodesMap = new Map(nodeList.map((n) => [n.id, n]));

    // Track which nodes have been placed
    const visitedNodeIds = new Set();

    // 1. Find ctrl chain roots and build their stacks
    const roots = findCtrlRoots(nodeList, idx);
    const ctrlStacks = roots.map((rootNode) => {
      const visited = new Set();
      const blocks = walkCtrlChain(rootNode.id, null, nodesMap, idx, visited);
      // Mark all visited nodes
      for (const id of visited) visitedNodeIds.add(id);
      return {
        rootNodeId: rootNode.id,
        blocks,
        isDataOnly: false,
        isOrphan: false,
      };
    });

    // 2. Pure data nodes (value, load, etc.) that weren't consumed inline
    const dataStacks = buildDataStacks(nodeList, visitedNodeIds, nodesMap, idx);

    // 3. Leftover nodes (disconnected ctrl fragments)
    const orphanStacks = buildOrphanStacks(nodeList, visitedNodeIds, nodesMap, idx);

    return {
      stacks: [...ctrlStacks, ...dataStacks, ...orphanStacks],
    };
  });

  return { blockTree };
}
