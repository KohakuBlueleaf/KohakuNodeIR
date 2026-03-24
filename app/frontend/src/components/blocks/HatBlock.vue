<script setup>
// HatBlock.vue — entry-point block with rounded top and bump on bottom.
// Used as the first block in a control chain that has no incoming ctrl edge.
// Supports right-click delete.

import { ref } from 'vue';
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
  history.pushState();
  // Remove all connections touching this node directly
  for (const [connId, conn] of graph.connections) {
    if (conn.fromNodeId === nodeId || conn.toNodeId === nodeId) {
      graph.connections.delete(connId);
    }
  }
  graph.nodes.delete(nodeId);
}
</script>

<template>
  <div
    class="hat-block"
    :data-block-node-id="block.nodeId"
    @contextmenu="onContextMenu"
  >
    <!-- Hat curve at top -->
    <div class="hat-top">
      <svg class="hat-curve" viewBox="0 0 200 20" preserveAspectRatio="none">
        <path d="M0,20 Q100,0 200,20 Z" fill="#cba6f7" />
      </svg>
      <div class="hat-header">
        <span class="hat-icon">&#x2605;</span>
        <span class="hat-label">{{ block.node.name }}</span>
        <span class="hat-type-badge">{{ block.node.type }}</span>
      </div>
    </div>

    <!-- Data output badges (hat block may expose data outputs) -->
    <div v-if="block.outputs.length" class="hat-outputs">
      <span v-for="out in block.outputs" :key="out" class="hat-output-tag">
        {{ out }}
      </span>
    </div>

    <!-- Bottom bump connector -->
    <div class="block-bump-bottom" />
  </div>

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
.hat-block {
  position: relative;
  min-width: 200px;
  background: #cba6f7;
  border-radius: 12px 12px 4px 4px;
  border: 1.5px solid #b4befe;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  font-size: 12px;
  color: #1e1e2e;
  user-select: none;
}

/* Hat-shaped top — SVG arc overlay */
.hat-top {
  position: relative;
  border-radius: 12px 12px 0 0;
  overflow: hidden;
}

.hat-curve {
  position: absolute;
  top: -1px;
  left: 0;
  width: 100%;
  height: 20px;
  pointer-events: none;
}

.hat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 14px 12px 8px;
  font-weight: 700;
  font-size: 12px;
}

.hat-icon {
  font-size: 10px;
  opacity: 0.7;
}

.hat-label {
  flex: 1;
  font-size: 13px;
  font-weight: 700;
  color: #1e1e2e;
}

.hat-type-badge {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: rgba(30, 30, 46, 0.25);
  border-radius: 3px;
  padding: 1px 5px;
  color: #1e1e2e;
}

.hat-outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 0 10px 8px;
}

.hat-output-tag {
  font-size: 10px;
  background: rgba(30, 30, 46, 0.2);
  border-radius: 3px;
  padding: 1px 6px;
  color: #1e1e2e;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

/* Bottom bump */
.block-bump-bottom {
  position: absolute;
  bottom: -8px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: #cba6f7;
  border-radius: 0 0 6px 6px;
  border: 1.5px solid #b4befe;
  border-top: none;
  z-index: 1;
}
</style>
