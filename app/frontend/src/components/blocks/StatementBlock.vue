<script setup>
// StatementBlock.vue — rectangular block for function/statement nodes.
// Has a notch on top (accepts bump from previous block) and a bump on bottom.
// Supports drag-to-reorder (useBlockDrag) and right-click delete.

import { ref } from 'vue';
import ReporterBlock from './ReporterBlock.vue';
import { useBlockDrag, draggingNodeId, dropTarget } from '../../composables/useBlockDrag.js';
import { useGraphStore } from '../../stores/graph.js';
import { useHistoryStore } from '../../stores/history.js';

const props = defineProps({
  block: {
    type: Object,
    required: true,
  },
});

// ── Stores ─────────────────────────────────────────────────────────────────────
const graph = useGraphStore();
const history = useHistoryStore();

// ── Drag ──────────────────────────────────────────────────────────────────────
const { onPointerDown } = useBlockDrag(props.block.nodeId);

// ── Context menu ─────────────────────────────────────────────────────────────
const contextMenu = ref(null); // { x, y }

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
  // Detach from chain first by bridging neighbors, then remove node
  // removeNode cascades all connection removal; we just need to bridge
  // prev→next before removing so the rest of the chain stays connected.
  const nodeId = props.block.nodeId;

  let prevConn = null;
  let nextConn = null;
  for (const conn of graph.connections.values()) {
    if (conn.portType !== 'control') continue;
    if (conn.toNodeId === nodeId) prevConn = conn;
    if (conn.fromNodeId === nodeId && !nextConn) nextConn = conn;
  }

  history.pushState();

  // Bridge: create edge from node-above to node-below before removing this one
  if (prevConn && nextConn) {
    // Use raw connections.set to bypass history push inside addConnection
    // We push state ourselves above. But addConnection also calls pushState.
    // To avoid double-push, we directly manipulate then removeNode:
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

  // removeNode clears all its connections and the node itself
  // But it also calls pushState internally — we already pushed above.
  // Use direct deletion to avoid duplicate history entries.
  // Remove connections touching nodeId
  for (const [connId, conn] of graph.connections) {
    if (conn.fromNodeId === nodeId || conn.toNodeId === nodeId) {
      graph.connections.delete(connId);
    }
  }
  graph.nodes.delete(nodeId);
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

// ── Category → color mapping (Catppuccin Mocha palette) ──────────────────────
const CATEGORY_COLORS = {
  'Control Flow': '#fab387',
  'Math':         '#89b4fa',
  'Comparison':   '#f9e2af',
  'String':       '#a6e3a1',
  'Display':      '#89dceb',
  'File':         '#cba6f7',
  'Data':         '#a6e3a1',
  'Convert':      '#74c7ec',
};

const TYPE_COLORS = {
  print:         '#89dceb',
  display:       '#89dceb',
  store:         '#a6e3a1',
  load:          '#a6e3a1',
  add:           '#89b4fa',
  subtract:      '#89b4fa',
  multiply:      '#89b4fa',
  divide:        '#89b4fa',
  greater_than:  '#f9e2af',
  less_than:     '#f9e2af',
  equal:         '#f9e2af',
  and:           '#f9e2af',
  not:           '#f9e2af',
  concat:        '#a6e3a1',
  format_string: '#a6e3a1',
  read_file:     '#cba6f7',
  write_file:    '#cba6f7',
  to_int:        '#74c7ec',
  to_float:      '#74c7ec',
  to_string:     '#74c7ec',
  merge:         '#6c7086',
};

function blockColor(block) {
  return TYPE_COLORS[block.node.type] ?? '#89b4fa';
}
</script>

<template>
  <!-- Drop-before indicator -->
  <div v-if="isDropTarget('before')" class="drop-indicator" />

  <div
    class="statement-block"
    :style="{ '--block-color': blockColor(block) }"
    :data-block-node-id="block.nodeId"
    :class="{ 'is-being-dragged': draggingNodeId === block.nodeId }"
    @contextmenu="onContextMenu"
  >
    <!-- Top notch indent (accepts snap from block above) -->
    <div class="block-notch-top" />

    <!-- Header row — drag handle -->
    <div
      class="block-header"
      @pointerdown.stop="onPointerDown"
    >
      <span class="drag-handle" title="Drag to reorder">&#x2630;</span>
      <span class="block-name">{{ block.node.name }}</span>
      <span class="block-type-badge">{{ block.node.type }}</span>
    </div>

    <!-- Ports row: inputs on left, outputs on right -->
    <div v-if="block.inputs.length || block.outputs.length" class="block-ports">
      <!-- Data inputs -->
      <div class="block-inputs">
        <div
          v-for="slot in block.inputs"
          :key="slot.portId"
          class="block-input-row"
        >
          <span class="port-label">{{ slot.portName }}</span>
          <ReporterBlock :slot="slot" />
        </div>
      </div>

      <!-- Data outputs -->
      <div v-if="block.outputs.length" class="block-outputs">
        <div
          v-for="out in block.outputs"
          :key="out"
          class="block-output-row"
        >
          <span class="port-label port-label--out">{{ out }}</span>
          <span class="output-arrow">&#x2192;</span>
        </div>
      </div>
    </div>

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
.statement-block {
  position: relative;
  min-width: 200px;
  background: color-mix(in srgb, var(--block-color) 14%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, var(--block-color) 60%, transparent);
  border-radius: 4px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
  font-size: 12px;
  color: #cdd6f4;
  user-select: none;
  padding-top: 8px;
  padding-bottom: 10px;
  transition: opacity 0.15s;
}

.statement-block.is-being-dragged {
  opacity: 0.4;
  pointer-events: none;
}

/* Top notch */
.block-notch-top {
  position: absolute;
  top: -1px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: #1e1e2e;
  border-radius: 6px 6px 0 0;
  border: 1.5px solid color-mix(in srgb, var(--block-color) 60%, transparent);
  border-bottom: none;
  z-index: 2;
}

.block-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px 6px;
  border-bottom: 1px solid color-mix(in srgb, var(--block-color) 25%, transparent);
  cursor: grab;
}

.block-header:active {
  cursor: grabbing;
}

.drag-handle {
  font-size: 11px;
  color: color-mix(in srgb, var(--block-color) 40%, #585b70);
  line-height: 1;
  flex-shrink: 0;
}

.block-name {
  font-weight: 700;
  font-size: 12px;
  color: var(--block-color);
  flex: 1;
}

.block-type-badge {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: color-mix(in srgb, var(--block-color) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--block-color) 30%, transparent);
  border-radius: 3px;
  padding: 1px 5px;
  color: color-mix(in srgb, var(--block-color) 80%, #cdd6f4);
}

/* Two-column port layout */
.block-ports {
  display: flex;
  gap: 8px;
  padding: 6px 10px 2px;
}

.block-inputs {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.block-outputs {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-end;
}

.block-input-row,
.block-output-row {
  display: flex;
  align-items: center;
  gap: 5px;
}

.port-label {
  font-size: 10px;
  color: #6c7086;
  white-space: nowrap;
  min-width: 32px;
}

.port-label--out {
  text-align: right;
  color: #6c7086;
}

.output-arrow {
  font-size: 10px;
  color: color-mix(in srgb, var(--block-color) 60%, #6c7086);
}

/* Bottom bump */
.block-bump-bottom {
  position: absolute;
  bottom: -8px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: color-mix(in srgb, var(--block-color) 14%, #1e1e2e);
  border-radius: 0 0 6px 6px;
  border: 1.5px solid color-mix(in srgb, var(--block-color) 60%, transparent);
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

<!-- Context menu is teleported to body; unscoped so it renders correctly -->
<style>
.context-menu {
  position: fixed;
  z-index: 9999;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  padding: 4px;
  min-width: 140px;
  font-size: 12px;
}

.context-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: #cdd6f4;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}

.context-menu-item:hover {
  background: #313244;
}

.context-menu-item--danger {
  color: #f38ba8;
}

.context-menu-item--danger:hover {
  background: color-mix(in srgb, #f38ba8 12%, #1e1e2e);
}

.context-menu-icon {
  font-size: 10px;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
}
</style>
