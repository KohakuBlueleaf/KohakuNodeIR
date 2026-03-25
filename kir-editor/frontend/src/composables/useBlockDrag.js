import { ref, shallowRef } from "vue";
import { useGraphStore } from "../stores/graph.js";
import { useHistoryStore } from "../stores/history.js";

// ── Shared drag state ──────────────────────────────────────────────────────────
// Exported as module-level refs so BlockCanvas can read them for the drop
// indicator overlay without prop-drilling.

/** @type {import('vue').Ref<string|null>} nodeId being dragged */
export const draggingNodeId = ref(null);

/**
 * Drop target for existing-block drags.
 * Normal reorder: { nodeId, position: 'before'|'after' }
 * Arm drop:       { armPortId, cBlockNodeId }
 * @type {import('vue').Ref<object|null>}
 */
export const dropTarget = ref(null);

/** @type {import('vue').ShallowRef<{x:number,y:number}|null>} ghost position (screen px) */
export const ghostPos = shallowRef(null);

// ── Internal module state ──────────────────────────────────────────────────────
let _startClientX = 0;
let _startClientY = 0;
let _hasMoved = false;
const DRAG_THRESHOLD = 5; // px before drag is considered started

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Collect all ctrl connections for a node in one pass.
 * Returns { prevConn, nextConn } where each may be null.
 *
 * prevConn: connection whose toNodeId === nodeId (ctrl)
 * nextConn: connection whose fromNodeId === nodeId, portType control (first)
 */
function getCtrlNeighbors(graph, nodeId) {
  let prevConn = null;
  let nextConn = null;
  for (const conn of graph.connections.values()) {
    if (conn.portType !== "control") continue;
    if (conn.toNodeId === nodeId) prevConn = conn;
    if (conn.fromNodeId === nodeId && !nextConn) nextConn = conn;
  }
  return { prevConn, nextConn };
}

/**
 * Detach a node from its ctrl chain. Bridges prev→next if both exist.
 * Does NOT push history — caller must do that first.
 */
function detachFromChain(graph, nodeId) {
  const { prevConn, nextConn } = getCtrlNeighbors(graph, nodeId);

  // Bridge: connect the node above directly to the node below
  if (prevConn && nextConn) {
    graph.addConnection(
      prevConn.fromNodeId,
      prevConn.fromPortId,
      nextConn.toNodeId,
      nextConn.toPortId,
      "control",
    );
  }

  // Remove the node's own ctrl edges (without pushing extra history)
  if (prevConn) graph.connections.delete(prevConn.id);
  if (nextConn) graph.connections.delete(nextConn.id);
}

/**
 * Find the last node in an arm's ctrl chain starting from a given ctrl output port.
 * Returns the nodeId of the last block in the chain, or null if the arm is empty.
 *
 * @param {object} graph
 * @param {string} armPortId - ctrl output port id on the C-block
 * @returns {string|null}
 */
function findArmTailNodeId(graph, armPortId) {
  let conn = null;
  for (const c of graph.connections.values()) {
    if (c.portType === "control" && c.fromPortId === armPortId) {
      conn = c;
      break;
    }
  }
  if (!conn) return null;

  let currentId = conn.toNodeId;
  const visited = new Set();
  while (currentId) {
    if (visited.has(currentId)) break;
    visited.add(currentId);
    const node = graph.nodes.get(currentId);
    if (!node) break;
    const outPort = node.controlPorts.outputs[0];
    if (!outPort) break;
    let nextConn = null;
    for (const c of graph.connections.values()) {
      if (
        c.portType === "control" &&
        c.fromNodeId === currentId &&
        c.fromPortId === outPort.id
      ) {
        nextConn = c;
        break;
      }
    }
    if (!nextConn) break;
    currentId = nextConn.toNodeId;
  }
  return currentId;
}

/**
 * Insert a node at the end of a C-block arm's ctrl chain.
 * Connects the C-block's arm port → node (if arm empty) or appends after tail.
 * Does NOT push history — caller must do that first.
 *
 * @param {object} graph
 * @param {string} nodeId       - node to insert into the arm
 * @param {string} armPortId    - ctrl output port of the C-block for this arm
 * @param {string} cBlockNodeId - id of the C-block node
 */
function insertIntoArm(graph, nodeId, armPortId, cBlockNodeId) {
  const insertNode = graph.nodes.get(nodeId);
  if (!insertNode) return;
  const insertInPort = insertNode.controlPorts.inputs[0];
  if (!insertInPort) return; // node has no ctrl input — cannot wire into chain

  const tailId = findArmTailNodeId(graph, armPortId);

  if (!tailId) {
    // Arm is empty: connect C-block arm port → node
    graph.addConnection(
      cBlockNodeId,
      armPortId,
      nodeId,
      insertInPort.id,
      "control",
    );
  } else {
    // Append after tail
    const tailNode = graph.nodes.get(tailId);
    if (!tailNode) return;
    const tailOut = tailNode.controlPorts.outputs[0];
    if (!tailOut) return;

    // Remove any existing connection from tail's output (should be none at tail, but be safe)
    for (const [cid, c] of graph.connections) {
      if (
        c.portType === "control" &&
        c.fromNodeId === tailId &&
        c.fromPortId === tailOut.id
      ) {
        graph.connections.delete(cid);
        break;
      }
    }
    graph.addConnection(tailId, tailOut.id, nodeId, insertInPort.id, "control");
  }
}

/**
 * Insert a node after `anchorNodeId` in the ctrl chain.
 * If anchorNodeId is null, node is just left floating (no insertion).
 * Does NOT push history — caller must do that first.
 *
 * @param {object} graph
 * @param {string} nodeId      - node to insert
 * @param {string|null} afterNodeId - insert after this node (null = floating)
 */
function insertAfterNode(graph, nodeId, afterNodeId) {
  if (!afterNodeId) return;

  const afterNode = graph.nodes.get(afterNodeId);
  const insertNode = graph.nodes.get(nodeId);
  if (!afterNode || !insertNode) return;

  // Ctrl output port of the anchor node (first one)
  const anchorOutPort = afterNode.controlPorts.outputs[0];
  // Ctrl input port of the node being inserted (first one)
  const insertInPort = insertNode.controlPorts.inputs[0];
  // Ctrl output port of the node being inserted
  const insertOutPort = insertNode.controlPorts.outputs[0];

  if (!anchorOutPort || !insertInPort) return;

  // Find what the anchor was connected to (its next node)
  let oldNextConn = null;
  for (const conn of graph.connections.values()) {
    if (
      conn.portType === "control" &&
      conn.fromNodeId === afterNodeId &&
      conn.fromPortId === anchorOutPort.id
    ) {
      oldNextConn = conn;
      break;
    }
  }

  // Remove anchor → old-next edge
  if (oldNextConn) graph.connections.delete(oldNextConn.id);

  // anchor → insert
  graph.addConnection(
    afterNodeId,
    anchorOutPort.id,
    nodeId,
    insertInPort.id,
    "control",
  );

  // insert → old-next (if exists and insertNode has an output)
  if (oldNextConn && insertOutPort) {
    graph.addConnection(
      nodeId,
      insertOutPort.id,
      oldNextConn.toNodeId,
      oldNextConn.toPortId,
      "control",
    );
  }
}

// ── Composable ────────────────────────────────────────────────────────────────

/**
 * useBlockDrag — attach to any block element to make it draggable for reordering.
 *
 * @param {string} nodeId
 * @returns {{ onPointerDown: Function }}
 */
export function useBlockDrag(nodeId) {
  const graph = useGraphStore();

  function onPointerDown(e) {
    // Left button only, skip if already dragging something
    if (e.button !== 0) return;
    if (draggingNodeId.value) return;

    _startClientX = e.clientX;
    _startClientY = e.clientY;
    _hasMoved = false;

    window.addEventListener("pointermove", _onPointerMove);
    window.addEventListener("pointerup", _onPointerUp);
  }

  function _onPointerMove(e) {
    const dx = e.clientX - _startClientX;
    const dy = e.clientY - _startClientY;

    if (!_hasMoved) {
      if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD)
        return;
      // Threshold crossed — start drag
      _hasMoved = true;
      draggingNodeId.value = nodeId;
    }

    ghostPos.value = { x: e.clientX, y: e.clientY };

    // Determine drop target from the element currently under the cursor
    // (excluding the ghost itself which has pointer-events:none)
    const el = document.elementFromPoint(e.clientX, e.clientY);

    // Check first: is the cursor inside a C-block arm body?
    const armEl = el?.closest("[data-arm-port-id]");
    if (armEl) {
      const armPortId = armEl.dataset.armPortId;
      const cBlockNodeId = armEl.dataset.armCBlockId;
      if (armPortId && cBlockNodeId && cBlockNodeId !== nodeId) {
        dropTarget.value = { armPortId, cBlockNodeId };
        return;
      }
    }

    // Otherwise: check for a normal block node reorder target
    const targetEl = el?.closest("[data-block-node-id]");
    if (targetEl && targetEl.dataset.blockNodeId !== nodeId) {
      const rect = targetEl.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      dropTarget.value = {
        nodeId: targetEl.dataset.blockNodeId,
        position: e.clientY < midY ? "before" : "after",
      };
    } else {
      dropTarget.value = null;
    }
  }

  function _onPointerUp() {
    window.removeEventListener("pointermove", _onPointerMove);
    window.removeEventListener("pointerup", _onPointerUp);

    if (!_hasMoved || !draggingNodeId.value) {
      draggingNodeId.value = null;
      ghostPos.value = null;
      dropTarget.value = null;
      return;
    }

    const target = dropTarget.value;
    const draggedId = draggingNodeId.value;

    // Reset shared state first
    draggingNodeId.value = null;
    ghostPos.value = null;
    dropTarget.value = null;

    if (!target) return;

    // Push history before mutating
    useHistoryStore().pushState();

    // Detach dragged node from its current position
    detachFromChain(graph, draggedId);

    // ── Arm drop: insert into a C-block arm ──────────────────────────────────
    if (target.armPortId) {
      insertIntoArm(graph, draggedId, target.armPortId, target.cBlockNodeId);
      return;
    }

    // Insert at drop position
    if (target.position === "after") {
      insertAfterNode(graph, draggedId, target.nodeId);
    } else {
      // Insert before target: find what comes before target, then insert after that
      let beforeTarget = null;
      for (const conn of graph.connections.values()) {
        if (conn.portType === "control" && conn.toNodeId === target.nodeId) {
          beforeTarget = conn.fromNodeId;
          break;
        }
      }
      insertAfterNode(graph, draggedId, beforeTarget ?? null);
      // Now insert between beforeTarget's new next and target
      // Re-do: insert draggedId such that target comes after it
      // The above already placed dragged after beforeTarget.
      // We still need to connect dragged → target.
      const draggedNode = graph.nodes.get(draggedId);
      const targetNode = graph.nodes.get(target.nodeId);
      if (draggedNode && targetNode) {
        const draggedOut = draggedNode.controlPorts.outputs[0];
        const targetIn = targetNode.controlPorts.inputs[0];
        if (draggedOut && targetIn) {
          // Remove any existing connection from dragged out
          for (const conn of graph.connections.values()) {
            if (
              conn.portType === "control" &&
              conn.fromNodeId === draggedId &&
              conn.fromPortId === draggedOut.id
            ) {
              graph.connections.delete(conn.id);
              break;
            }
          }
          // Remove any existing ctrl-in connection to target
          for (const conn of graph.connections.values()) {
            if (
              conn.portType === "control" &&
              conn.toNodeId === target.nodeId &&
              conn.toPortId === targetIn.id
            ) {
              graph.connections.delete(conn.id);
              break;
            }
          }
          graph.addConnection(
            draggedId,
            draggedOut.id,
            target.nodeId,
            targetIn.id,
            "control",
          );
        }
      }
    }
  }

  return { onPointerDown };
}
