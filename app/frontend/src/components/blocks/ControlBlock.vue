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

        <!-- Arm body: indented BlockStack -->
        <div class="ctrl-arm-body">
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
