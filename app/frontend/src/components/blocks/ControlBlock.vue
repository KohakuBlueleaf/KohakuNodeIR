<script setup>
// ControlBlock.vue — C-shaped block for branch / switch / parallel / loop nodes.
// Wraps child BlockStack arms inside a Scratch-style C shape built from CSS divs.
// Supports drag-to-reorder and right-click delete.

import { ref } from 'vue';
import ReporterBlock from './ReporterBlock.vue';
import BlockStack    from './BlockStack.vue';
import { useBlockDrag, draggingNodeId, dropTarget } from '../../composables/useBlockDrag.js';
import { useGraphStore } from '../../stores/graph.js';
import { useHistoryStore } from '../../stores/history.js';
import { useNodeRegistryStore } from '../../stores/nodeRegistry.js';

const props = defineProps({
  block: {
    type: Object,
    required: true,
  },
});

// ── Stores ─────────────────────────────────────────────────────────────────────
const graph = useGraphStore();
const history = useHistoryStore();
const registry = useNodeRegistryStore();

// ── Drag ──────────────────────────────────────────────────────────────────────
const { onPointerDown } = useBlockDrag(props.block.nodeId);

// ── Context menu ──────────────────────────────────────────────────────────────
const contextMenu = ref(null);

function onContextMenu(e) {
  e.preventDefault();
  e.stopPropagation();
  contextMenu.value = { x: e.clientX, y: e.clientY };
  window.addEventListener('pointerdown', dismissContextMenu, { once: true });
}

function dismissContextMenu() {
  contextMenu.value = null;
}

function deleteBlock() {
  contextMenu.value = null;
  const nodeId = props.block.nodeId;

  // Bridge prev→next across this node before deleting
  let prevConn = null;
  let nextConn = null;
  for (const conn of graph.connections.values()) {
    if (conn.portType !== 'control') continue;
    if (conn.toNodeId === nodeId) prevConn = conn;
    if (conn.fromNodeId === nodeId && !nextConn) nextConn = conn;
  }

  history.pushState();

  if (prevConn && nextConn) {
    const bridgeId = `conn-bridge-${Date.now()}`;
    graph.connections.set(bridgeId, {
      id: bridgeId,
      fromNodeId: prevConn.fromNodeId,
      fromPortId: prevConn.fromPortId,
      toNodeId: nextConn.toNodeId,
      toPortId: nextConn.toPortId,
      portType: 'control',
    });
  }

  for (const [connId, conn] of graph.connections) {
    if (conn.fromNodeId === nodeId || conn.toNodeId === nodeId) {
      graph.connections.delete(connId);
    }
  }
  graph.nodes.delete(nodeId);
}

// ── Arm palette drag-and-drop ─────────────────────────────────────────────────

/**
 * Find the last node in an arm's ctrl chain starting from `armPortId`.
 * Returns the nodeId of the last block in the chain, or null if the arm is empty.
 */
function findArmTailNodeId(armPortId) {
  // Find the connection leaving this arm port
  let conn = null;
  for (const c of graph.connections.values()) {
    if (c.portType === 'control' && c.fromPortId === armPortId) {
      conn = c;
      break;
    }
  }
  if (!conn) return null; // arm is empty

  // Walk the chain until we find a node with no ctrl output connection
  let currentId = conn.toNodeId;
  const visited = new Set();
  while (currentId) {
    if (visited.has(currentId)) break;
    visited.add(currentId);
    const node = graph.nodes.get(currentId);
    if (!node) break;
    // Find what comes after this node on its first ctrl output
    const outPort = node.controlPorts.outputs[0];
    if (!outPort) break;
    let nextConn = null;
    for (const c of graph.connections.values()) {
      if (c.portType === 'control' && c.fromNodeId === currentId && c.fromPortId === outPort.id) {
        nextConn = c;
        break;
      }
    }
    if (!nextConn) break; // currentId is the tail
    currentId = nextConn.toNodeId;
  }
  return currentId;
}

/**
 * Wire a newly created node into an arm's ctrl chain without pushing extra
 * history entries (caller already pushed, or addNode already pushed).
 * Uses graph.connections.set directly to bypass addConnection's pushState.
 *
 * @param {string} newNodeId    - node just created
 * @param {string} armPortId    - ctrl output port of the C-block for this arm
 * @param {string} cBlockNodeId - the C-block (branch/switch/parallel) node id
 */
function wireNodeIntoArm(newNodeId, armPortId, cBlockNodeId) {
  const newNode = graph.nodes.get(newNodeId);
  if (!newNode) return;

  const newNodeIn = newNode.controlPorts.inputs[0];
  if (!newNodeIn) return; // node has no ctrl input — cannot wire into chain

  const tailId = findArmTailNodeId(armPortId);

  function makeConn(fromNodeId, fromPortId, toNodeId, toPortId) {
    const id = `conn-arm-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    graph.connections.set(id, { id, fromNodeId, fromPortId, toNodeId, toPortId, portType: 'control' });
  }

  if (!tailId) {
    // Arm is empty: connect C-block's arm port → new node's ctrl input
    makeConn(cBlockNodeId, armPortId, newNodeId, newNodeIn.id);
  } else {
    // Arm has existing blocks: append after the tail
    const tailNode = graph.nodes.get(tailId);
    if (!tailNode) return;
    const tailOut = tailNode.controlPorts.outputs[0];
    if (!tailOut) return;

    // Remove any existing connection from tail's output (should be empty at tail, but be safe)
    for (const [cid, c] of graph.connections) {
      if (c.portType === 'control' && c.fromNodeId === tailId && c.fromPortId === tailOut.id) {
        graph.connections.delete(cid);
        break;
      }
    }
    makeConn(tailId, tailOut.id, newNodeId, newNodeIn.id);
  }
}

function onArmDragOver(e) {
  if (!e.dataTransfer.types.includes('application/x-block-type')) return;
  e.preventDefault();
  e.stopPropagation();
  e.dataTransfer.dropEffect = 'copy';
}

function onArmDrop(e, armPortId) {
  e.preventDefault();
  e.stopPropagation();
  const typeName = e.dataTransfer.getData('application/x-block-type');
  if (!typeName || !armPortId) return;

  try {
    // graph.addNode() pushes history internally before adding, which captures
    // the pre-drop state as the undo checkpoint.
    const nodeData = registry.createNodeData(typeName, 0, 0);
    const newNodeId = graph.addNode(nodeData);
    wireNodeIntoArm(newNodeId, armPortId, props.block.nodeId);
  } catch (err) {
    console.warn('[ControlBlock] arm drop failed:', err.message);
  }
}

// ── Drop indicator ────────────────────────────────────────────────────────────
function isDropTarget(position) {
  return (
    draggingNodeId.value !== null &&
    draggingNodeId.value !== props.block.nodeId &&
    dropTarget.value?.nodeId === props.block.nodeId &&
    dropTarget.value?.position === position
  );
}

// ── Colors ────────────────────────────────────────────────────────────────────
const TYPE_COLORS = {
  branch:   '#fab387',
  switch:   '#f9e2af',
  parallel: '#94e2d5',
  loop:     '#cba6f7',
};

function blockColor(block) {
  return TYPE_COLORS[block.type] ?? '#fab387';
}

function arms(block) {
  if (block.arms) return block.arms;
  if (block.body) return [{ label: 'body', blocks: block.body }];
  return [];
}
</script>

<template>
  <!-- Drop-before indicator -->
  <div v-if="isDropTarget('before')" class="drop-indicator" />

  <div
    class="control-block"
    :style="{ '--ctrl-color': blockColor(block) }"
    :data-block-node-id="block.nodeId"
    :class="{ 'is-being-dragged': draggingNodeId === block.nodeId }"
    @contextmenu="onContextMenu"
  >
    <!-- Top notch -->
    <div class="block-notch-top" />

    <!-- ── Header section ── -->
    <div class="ctrl-header" @pointerdown.stop="onPointerDown">
      <div class="ctrl-header-row">
        <span class="drag-handle" title="Drag to reorder">&#x2630;</span>
        <span class="ctrl-icon">
          <template v-if="block.type === 'branch'">&#x2ADD;</template>
          <template v-else-if="block.type === 'switch'">&#x25A6;</template>
          <template v-else-if="block.type === 'parallel'">&#x2261;</template>
          <template v-else>&#x21BB;</template>
        </span>
        <span class="ctrl-name">{{ block.node.name }}</span>
        <span class="ctrl-type-badge">{{ block.node.type }}</span>
      </div>

      <!-- Condition / value input slots (inline reporter slots) -->
      <div v-if="block.inputs.length" class="ctrl-inputs">
        <div
          v-for="slot in block.inputs"
          :key="slot.portId"
          class="ctrl-input-row"
        >
          <span class="ctrl-port-label">{{ slot.portName }}</span>
          <ReporterBlock :slot="slot" />
        </div>
      </div>
    </div>

    <!-- ── Arms (C body) ── -->
    <div class="ctrl-arms">
      <div
        v-for="(arm, i) in arms(block)"
        :key="arm.portId ?? i"
        class="ctrl-arm"
      >
        <!-- Arm label (left sidebar) -->
        <div class="ctrl-arm-label">
          <span class="arm-label-text">{{ arm.label }}</span>
        </div>

        <!-- Arm body: indented BlockStack — accepts palette drops -->
        <div
          class="ctrl-arm-body"
          :data-arm-port-id="arm.portId"
          :data-arm-c-block-id="block.nodeId"
          @dragover="onArmDragOver"
          @drop="onArmDrop($event, arm.portId)"
        >
          <BlockStack :blocks="arm.blocks" />
        </div>
      </div>
    </div>

    <!-- ── Closing bar ── -->
    <div class="ctrl-footer" />

    <!-- Bottom bump connector -->
    <div class="block-bump-bottom" />
  </div>

  <!-- Drop-after indicator -->
  <div v-if="isDropTarget('after')" class="drop-indicator" />

  <!-- Context menu -->
  <Teleport to="body">
    <div
      v-if="contextMenu"
      class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      @pointerdown.stop
    >
      <button class="context-menu-item context-menu-item--danger" @click="deleteBlock">
        <span class="context-menu-icon">&#x2715;</span>
        Delete block
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.control-block {
  position: relative;
  min-width: 250px;
  background: color-mix(in srgb, var(--ctrl-color) 12%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, var(--ctrl-color) 55%, transparent);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  font-size: 12px;
  color: #cdd6f4;
  user-select: none;
  padding-top: 8px;
  transition: opacity 0.15s;
}

.control-block.is-being-dragged {
  opacity: 0.4;
  pointer-events: none;
}

/* Notch at top */
.block-notch-top {
  position: absolute;
  top: -1px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: #1e1e2e;
  border-radius: 6px 6px 0 0;
  border: 1.5px solid color-mix(in srgb, var(--ctrl-color) 55%, transparent);
  border-bottom: none;
  z-index: 2;
}

/* Header */
.ctrl-header {
  padding: 4px 12px 8px;
  border-bottom: 1.5px solid color-mix(in srgb, var(--ctrl-color) 30%, transparent);
  cursor: grab;
}

.ctrl-header:active {
  cursor: grabbing;
}

.ctrl-header-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.drag-handle {
  font-size: 11px;
  color: color-mix(in srgb, var(--ctrl-color) 40%, #585b70);
  line-height: 1;
  flex-shrink: 0;
}

.ctrl-icon {
  font-size: 14px;
  color: var(--ctrl-color);
  line-height: 1;
}

.ctrl-name {
  font-weight: 700;
  font-size: 12px;
  color: var(--ctrl-color);
  flex: 1;
}

.ctrl-type-badge {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: color-mix(in srgb, var(--ctrl-color) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--ctrl-color) 30%, transparent);
  border-radius: 3px;
  padding: 1px 5px;
  color: color-mix(in srgb, var(--ctrl-color) 80%, #cdd6f4);
}

.ctrl-inputs {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 4px;
}

.ctrl-input-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ctrl-port-label {
  font-size: 10px;
  color: #6c7086;
  min-width: 40px;
}

/* Arms container */
.ctrl-arms {
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* Single arm */
.ctrl-arm {
  display: flex;
  align-items: stretch;
  border-top: 1px solid color-mix(in srgb, var(--ctrl-color) 20%, transparent);
}

/* Vertical label strip — the "C" left wall */
.ctrl-arm-label {
  width: 24px;
  background: color-mix(in srgb, var(--ctrl-color) 20%, #181825);
  border-right: 1.5px solid color-mix(in srgb, var(--ctrl-color) 40%, transparent);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 6px;
  flex-shrink: 0;
}

.arm-label-text {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ctrl-color);
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  opacity: 0.85;
}

/* Arm body */
.ctrl-arm-body {
  flex: 1;
  padding: 8px 8px 8px 10px;
  min-height: 40px;
}

/* Closing footer bar */
.ctrl-footer {
  height: 12px;
  background: color-mix(in srgb, var(--ctrl-color) 18%, #181825);
  border-top: 1.5px solid color-mix(in srgb, var(--ctrl-color) 35%, transparent);
  border-radius: 0 0 4px 4px;
}

/* Bottom bump */
.block-bump-bottom {
  position: absolute;
  bottom: -8px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: color-mix(in srgb, var(--ctrl-color) 18%, #181825);
  border-radius: 0 0 6px 6px;
  border: 1.5px solid color-mix(in srgb, var(--ctrl-color) 55%, transparent);
  border-top: none;
  z-index: 1;
}

/* Drop indicator line */
.drop-indicator {
  height: 3px;
  border-radius: 2px;
  background: #89b4fa;
  box-shadow: 0 0 6px #89b4fa;
  margin: 1px 4px;
}
</style>
