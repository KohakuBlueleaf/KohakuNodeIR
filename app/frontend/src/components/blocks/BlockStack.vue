<script setup>
// BlockStack.vue — renders a vertical list of Block objects.
// Used for the top-level stacks on the canvas AND inside C-block arms.
// Mutual recursion with ControlBlock is handled via defineAsyncComponent.

import { ref, defineAsyncComponent } from 'vue';
import HatBlock       from './HatBlock.vue';
import StatementBlock from './StatementBlock.vue';
import { useGraphStore } from '../../stores/graph.js';
import { useHistoryStore } from '../../stores/history.js';

// Async import breaks the circular dependency: BlockStack -> ControlBlock -> BlockStack
const ControlBlock = defineAsyncComponent(() => import('./ControlBlock.vue'));

const props = defineProps({
  /** Array of Block objects from blockTree.js */
  blocks: {
    type: Array,
    required: true,
  },
});

// ── Reporter node inline delete (right-click) ─────────────────────────────────
const graph = useGraphStore();
const history = useHistoryStore();
const reporterContextMenu = ref(null); // { x, y, nodeId }

function onReporterContextMenu(e, nodeId) {
  e.preventDefault();
  e.stopPropagation();
  reporterContextMenu.value = { x: e.clientX, y: e.clientY, nodeId };
  window.addEventListener('pointerdown', dismissReporterMenu, { once: true });
}

function dismissReporterMenu() {
  reporterContextMenu.value = null;
}

function deleteReporterNode() {
  if (!reporterContextMenu.value) return;
  const nodeId = reporterContextMenu.value.nodeId;
  reporterContextMenu.value = null;
  history.pushState();
  for (const [connId, conn] of graph.connections) {
    if (conn.fromNodeId === nodeId || conn.toNodeId === nodeId) {
      graph.connections.delete(connId);
    }
  }
  graph.nodes.delete(nodeId);
}
</script>

<template>
  <div class="block-stack">
    <template v-for="block in blocks" :key="block.nodeId">
      <!-- Hat block (entry point / namespace label) -->
      <HatBlock
        v-if="block.type === 'hat'"
        :block="block"
        class="stack-item"
      />

      <!-- C-blocks: branch / switch / parallel / loop -->
      <ControlBlock
        v-else-if="block.type === 'branch' || block.type === 'switch' || block.type === 'parallel' || block.type === 'loop'"
        :block="block"
        class="stack-item"
      />

      <!-- Value / reporter nodes shown as standalone reporter pill -->
      <div
        v-else-if="block.type === 'value' || block.type === 'reporter'"
        class="stack-item reporter-stack-item"
        :data-block-node-id="block.nodeId"
        @contextmenu="onReporterContextMenu($event, block.nodeId)"
      >
        <span class="reporter-node-label">{{ block.node.name }}</span>
        <span class="reporter-node-value">
          {{ block.node.properties?.value ?? block.node.dataPorts?.outputs?.[0]?.defaultValue ?? '—' }}
        </span>
      </div>

      <!-- Default: statement block -->
      <StatementBlock
        v-else
        :block="block"
        class="stack-item"
      />
    </template>

    <!-- Empty arm placeholder -->
    <div v-if="!blocks.length" class="stack-empty">
      <span class="stack-empty-label">empty</span>
    </div>
  </div>

  <!-- Reporter node context menu -->
  <Teleport to="body">
    <div
      v-if="reporterContextMenu"
      class="context-menu"
      :style="{ left: reporterContextMenu.x + 'px', top: reporterContextMenu.y + 'px' }"
      @pointerdown.stop
    >
      <button class="context-menu-item context-menu-item--danger" @click="deleteReporterNode">
        <span class="context-menu-icon">&#x2715;</span>
        Delete block
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.block-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Each block item needs relative positioning so bumps/notches layer correctly */
.stack-item {
  position: relative;
}

/* Standalone reporter node (pure data, no ctrl) */
.reporter-stack-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: color-mix(in srgb, #a6e3a1 14%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, #a6e3a1 50%, transparent);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 11px;
  color: #a6e3a1;
  user-select: none;
  align-self: flex-start;
  cursor: context-menu;
}

.reporter-stack-item:hover {
  background: color-mix(in srgb, #a6e3a1 22%, #1e1e2e);
}

.reporter-node-label {
  font-weight: 600;
  color: #6c7086;
  font-size: 10px;
}

.reporter-node-value {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: #a6e3a1;
}

/* Empty arm indicator */
.stack-empty {
  min-width: 120px;
  min-height: 28px;
  border: 1.5px dashed #313244;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stack-empty-label {
  font-size: 10px;
  color: #45475a;
  font-style: italic;
}
</style>
