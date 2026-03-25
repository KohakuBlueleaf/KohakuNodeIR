import { reactive, computed } from "vue";
import { defineStore } from "pinia";
import { snapToGrid, snapPoint } from "../utils/grid.js";
import { useHistoryStore } from "./history.js";

// --- Constants ---
const PORT_PADDING = 30; // px from edge before first ctrl port
const HEADER_H = 32;
const CTRL_ROW_H = 18;
const DATA_ROW_H = 28; // fixed row height for each data port

let _idCounter = 0;
function generateId(prefix = "id") {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${++_idCounter}-${Date.now()}`;
}

export const useGraphStore = defineStore("graph", () => {
  // ---- State ----
  // Using reactive Maps so Vue can track mutations
  const nodes = reactive(new Map()); // Map<string, NodeData>
  const connections = reactive(new Map()); // Map<string, ConnectionData>

  // ---- Computed ----
  const nodeList = computed(() => Array.from(nodes.values()));
  const connectionList = computed(() => Array.from(connections.values()));

  // ---- Node Methods ----

  /**
   * Add a node to the graph.
   * @param {object} nodeData - Partial NodeData; id is generated if absent.
   * @returns {string} The assigned node id.
   */
  function addNode(nodeData) {
    useHistoryStore().pushState();
    const id = nodeData.id ?? generateId("node");
    const snapped = snapPoint(nodeData.x ?? 0, nodeData.y ?? 0);
    const node = {
      id,
      type: nodeData.type ?? "function",
      name: nodeData.name ?? "Node",
      x: snapped.x,
      y: snapped.y,
      width: snapToGrid(nodeData.width ?? 160),
      height: snapToGrid(nodeData.height ?? 120),
      dataPorts: {
        inputs: nodeData.dataPorts?.inputs ?? [],
        outputs: nodeData.dataPorts?.outputs ?? [],
      },
      controlPorts: {
        inputs: nodeData.controlPorts?.inputs ?? [],
        outputs: nodeData.controlPorts?.outputs ?? [],
      },
      properties: nodeData.properties ?? {},
    };
    nodes.set(id, node);
    return id;
  }

  /**
   * Remove a node and all connections attached to it.
   * @param {string} id
   */
  function removeNode(id) {
    if (!nodes.has(id)) return;
    useHistoryStore().pushState();
    // Remove every connection that touches this node
    for (const [connId, conn] of connections) {
      if (conn.fromNodeId === id || conn.toNodeId === id) {
        connections.delete(connId);
      }
    }
    nodes.delete(id);
  }

  /**
   * Update a node's position, snapping to grid.
   * @param {string} id
   * @param {number} x
   * @param {number} y
   */
  function updateNodePosition(id, x, y) {
    const node = nodes.get(id);
    if (!node) return;
    const snapped = snapPoint(x, y);
    node.x = snapped.x;
    node.y = snapped.y;
  }

  /**
   * Compute the minimum height required to display all ports for a node.
   * Matches the formula used by BaseNode.vue's minHeight CSS.
   * @param {object} node
   * @returns {number}
   */
  function computeMinHeight(node) {
    const hasCtrlIn = node.controlPorts.inputs.length > 0;
    const hasCtrlOut = node.controlPorts.outputs.length > 0;
    const dataRows = Math.max(
      node.dataPorts.inputs.length,
      node.dataPorts.outputs.length,
    );
    return (
      (hasCtrlIn ? CTRL_ROW_H : 0) +
      HEADER_H +
      dataRows * DATA_ROW_H +
      (hasCtrlOut ? CTRL_ROW_H : 0) +
      8
    );
  }

  /**
   * Update a node's size, snapping each dimension to grid.
   * Height is clamped to never go below the minimum needed to display all ports.
   * @param {string} id
   * @param {number} width
   * @param {number} height
   */
  function updateNodeSize(id, width, height) {
    const node = nodes.get(id);
    if (!node) return;
    const minH = computeMinHeight(node);
    node.width = snapToGrid(width);
    node.height = snapToGrid(Math.max(height, minH));
  }

  /**
   * Recalculate node height to fit all ports. Call after adding/removing ports.
   */
  function autoResizeHeight(id) {
    const node = nodes.get(id);
    if (!node) return;
    const minH = computeMinHeight(node);
    node.height = snapToGrid(Math.max(minH, node.height));
  }

  // ---- Connection Methods ----

  /**
   * Add a connection between two ports.
   * @param {string} fromNodeId
   * @param {string} fromPortId
   * @param {string} toNodeId
   * @param {string} toPortId
   * @param {'data'|'control'} portType
   * @returns {string|null} Connection id, or null if invalid.
   */
  function addConnection(fromNodeId, fromPortId, toNodeId, toPortId, portType) {
    if (!canConnect(fromNodeId, fromPortId, toNodeId, toPortId, portType)) {
      return null;
    }
    useHistoryStore().pushState();
    const id = generateId("conn");
    const connection = {
      id,
      fromNodeId,
      fromPortId,
      toNodeId,
      toPortId,
      portType,
    };
    connections.set(id, connection);
    return id;
  }

  /**
   * Remove a connection by id.
   * @param {string} id
   */
  function removeConnection(id) {
    if (!connections.has(id)) return;
    useHistoryStore().pushState();
    connections.delete(id);
  }

  /**
   * Get all connections that involve a given node.
   * @param {string} nodeId
   * @returns {ConnectionData[]}
   */
  function getNodeConnections(nodeId) {
    const result = [];
    for (const conn of connections.values()) {
      if (conn.fromNodeId === nodeId || conn.toNodeId === nodeId) {
        result.push(conn);
      }
    }
    return result;
  }

  /**
   * Get all connections that involve a given port.
   * @param {string} portId
   * @returns {ConnectionData[]}
   */
  function getPortConnections(portId) {
    const result = [];
    for (const conn of connections.values()) {
      if (conn.fromPortId === portId || conn.toPortId === portId) {
        result.push(conn);
      }
    }
    return result;
  }

  /**
   * Remove all nodes and connections.
   */
  function clear() {
    nodes.clear();
    connections.clear();
  }

  // ---- Port Position ----

  /**
   * Compute the canvas-space {x, y} of a port on a node.
   *
   * Layout rules:
   *   Data input ports  — left edge,   evenly spaced vertically
   *   Data output ports — right edge,  evenly spaced vertically
   *   Control input ports  — top edge,    evenly spaced horizontally
   *   Control output ports — bottom edge, evenly spaced horizontally
   *
   * @param {string} nodeId
   * @param {string} portId
   * @returns {{ x: number, y: number } | null}
   */
  function getPortPosition(nodeId, portId) {
    const node = nodes.get(nodeId);
    if (!node) return null;

    const { x, y, width, height, dataPorts, controlPorts } = node;

    // Helper: evenly space `count` items over `span`, return position of `index`
    function evenSpacing(index, count, span) {
      if (count === 1) return span / 2;
      return PORT_PADDING + index * ((span - PORT_PADDING * 2) / (count - 1));
    }

    // Row-based layout: fixed position per port index (doesn't depend on node height)
    const hasCtrlIn = controlPorts.inputs.length > 0;

    // Data port Y = ctrlIn area + header + row center
    function dataRowY(index) {
      return (
        (hasCtrlIn ? CTRL_ROW_H : 0) +
        HEADER_H +
        index * DATA_ROW_H +
        DATA_ROW_H / 2
      );
    }

    // Data inputs — left edge
    const dataInIndex = dataPorts.inputs.findIndex((p) => p.id === portId);
    if (dataInIndex !== -1) {
      return { x, y: y + dataRowY(dataInIndex) };
    }

    // Data outputs — right edge
    const dataOutIndex = dataPorts.outputs.findIndex((p) => p.id === portId);
    if (dataOutIndex !== -1) {
      return { x: x + width, y: y + dataRowY(dataOutIndex) };
    }

    // Control inputs — top edge
    // The diamond center sits at the vertical midpoint of the ctrl-row div
    // (CTRL_ROW_H / 2 = 9px below the top of the node).
    const ctrlInIndex = controlPorts.inputs.findIndex((p) => p.id === portId);
    if (ctrlInIndex !== -1) {
      return {
        x: x + evenSpacing(ctrlInIndex, controlPorts.inputs.length, width),
        y: y + CTRL_ROW_H / 2,
      };
    }

    // Control outputs — bottom edge
    // Use the effective height: max of stored height and the CSS minHeight
    // so the wire anchor matches the visual bottom of the node even when the
    // node has more data ports than the stored height accounts for.
    // The diamond center sits CTRL_ROW_H / 2 px above the bottom of the node.
    const ctrlOutIndex = controlPorts.outputs.findIndex((p) => p.id === portId);
    if (ctrlOutIndex !== -1) {
      const effectiveHeight = Math.max(height, computeMinHeight(node));
      return {
        x: x + evenSpacing(ctrlOutIndex, controlPorts.outputs.length, width),
        y: y + effectiveHeight - CTRL_ROW_H / 2,
      };
    }

    return null;
  }

  // ---- Validation ----

  /**
   * Determine whether a proposed connection is valid.
   *
   * Rules:
   *  - portType must be 'data' or 'control'
   *  - No self-loops (fromNodeId !== toNodeId)
   *  - No duplicate connections (same four endpoint ids)
   *  - Both source port and target port must exist on their respective nodes
   *  - data  port must connect to data  port
   *  - control port must connect to control port
   *  - From-port must be an output, to-port must be an input
   *
   * @param {string} fromNodeId
   * @param {string} fromPortId
   * @param {string} toNodeId
   * @param {string} toPortId
   * @param {'data'|'control'} portType
   * @returns {boolean}
   */
  function canConnect(fromNodeId, fromPortId, toNodeId, toPortId, portType) {
    if (portType !== "data" && portType !== "control") return false;

    // No self-loops
    if (fromNodeId === toNodeId) return false;

    const fromNode = nodes.get(fromNodeId);
    const toNode = nodes.get(toNodeId);
    if (!fromNode || !toNode) return false;

    // Validate port existence and direction
    if (portType === "data") {
      const fromIsOutput = fromNode.dataPorts.outputs.some(
        (p) => p.id === fromPortId,
      );
      const toIsInput = toNode.dataPorts.inputs.some((p) => p.id === toPortId);
      if (!fromIsOutput || !toIsInput) return false;
    } else {
      // control
      const fromIsOutput = fromNode.controlPorts.outputs.some(
        (p) => p.id === fromPortId,
      );
      const toIsInput = toNode.controlPorts.inputs.some(
        (p) => p.id === toPortId,
      );
      if (!fromIsOutput || !toIsInput) return false;
    }

    // No duplicate connections
    for (const conn of connections.values()) {
      if (
        conn.fromNodeId === fromNodeId &&
        conn.fromPortId === fromPortId &&
        conn.toNodeId === toNodeId &&
        conn.toPortId === toPortId
      ) {
        return false;
      }
    }

    return true;
  }

  // ---- Drag / resize history helpers ----

  /**
   * Push a history snapshot before a drag begins.
   * Call once on mousedown, not on every mousemove.
   */
  function beginMove() {
    useHistoryStore().pushState();
  }

  /**
   * Push a history snapshot before a resize begins.
   * Call once on mousedown, not on every mousemove.
   */
  function beginResize() {
    useHistoryStore().pushState();
  }

  // ---- Serialization helpers (used by history store) ----

  /**
   * Return a plain-object snapshot of the current graph state.
   * @returns {{ nodes: object[], connections: object[] }}
   */
  function serialize() {
    return {
      nodes: Array.from(nodes.values()).map((n) => ({
        ...n,
        dataPorts: {
          inputs: n.dataPorts.inputs.map((p) => ({ ...p })),
          outputs: n.dataPorts.outputs.map((p) => ({ ...p })),
        },
        controlPorts: {
          inputs: n.controlPorts.inputs.map((p) => ({ ...p })),
          outputs: n.controlPorts.outputs.map((p) => ({ ...p })),
        },
        properties: { ...n.properties },
      })),
      connections: Array.from(connections.values()).map((c) => ({ ...c })),
    };
  }

  /**
   * Restore graph state from a plain-object snapshot (from serialize()).
   * @param {{ nodes: object[], connections: object[] }} snapshot
   */
  function deserialize(snapshot) {
    nodes.clear();
    connections.clear();
    for (const n of snapshot.nodes) {
      nodes.set(n.id, {
        ...n,
        dataPorts: {
          inputs: n.dataPorts.inputs.map((p) => ({ ...p })),
          outputs: n.dataPorts.outputs.map((p) => ({ ...p })),
        },
        controlPorts: {
          inputs: n.controlPorts.inputs.map((p) => ({ ...p })),
          outputs: n.controlPorts.outputs.map((p) => ({ ...p })),
        },
        properties: { ...n.properties },
      });
    }
    for (const c of snapshot.connections) {
      connections.set(c.id, { ...c });
    }
  }

  return {
    // State
    nodes,
    connections,

    // Computed
    nodeList,
    connectionList,

    // Node methods
    addNode,
    removeNode,
    updateNodePosition,
    updateNodeSize,
    autoResizeHeight,
    beginMove,
    beginResize,

    // Connection methods
    addConnection,
    removeConnection,
    getNodeConnections,
    getPortConnections,
    clear,

    // Utilities
    getPortPosition,
    canConnect,
    serialize,
    deserialize,
  };
});
