<script setup>
/**
 * MergeNode — body content for 'merge' type nodes.
 * Rendered inside BaseNode's #body slot via NodeRenderer.
 *
 * Layout:
 *   - Lists current control-input ports (labelled "in 0", "in 1", …)
 *   - A "+" button to add another control input
 *   - Single control output at the bottom (handled by port chrome in BaseNode,
 *     but we show a label so the user sees it in the body too)
 *
 * The node intentionally stays compact — no data ports.
 *
 * Emits:
 *   - add-control-input   — request to add a new control-input port
 */

import { computed } from 'vue';

const props = defineProps({
  node: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(['add-control-input']);

const inputPorts = computed(() => props.node.controlPorts?.inputs ?? []);
</script>

<template>
  <div class="merge-body">

    <!-- Control inputs list -->
    <div class="ports-list">
      <div
        v-for="port in inputPorts"
        :key="port.id"
        class="port-row"
      >
        <span class="port-dot" />
        <span class="port-name">{{ port.name }}</span>
      </div>
    </div>

    <!-- Add input button -->
    <button
      class="add-btn"
      title="Add control input"
      @click.stop="emit('add-control-input')"
      @pointerdown.stop
    >
      <span class="add-icon">+</span>
      <span>add input</span>
    </button>

    <!-- Output indicator -->
    <div class="output-row">
      <span class="out-label">out</span>
      <span class="port-dot port-dot--out" />
    </div>

  </div>
</template>

<style scoped>
.merge-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
}

/* Port list */
.ports-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.port-row {
  display: flex;
  align-items: center;
  gap: 5px;
  min-height: 16px;
}

.port-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #fab387; /* --port-control */
  flex-shrink: 0;
}

.port-name {
  color: #bac2de;
  font-size: 10px;
}

/* Add button */
.add-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px dashed #45475a;
  background: transparent;
  color: #6c7086;
  font-size: 10px;
  cursor: pointer;
  transition: border-color 0.12s, color 0.12s;
  width: 100%;
  justify-content: center;
}
.add-btn:hover {
  border-color: #fab387;
  color: #fab387;
}
.add-icon {
  font-size: 13px;
  line-height: 1;
  font-weight: 700;
}

/* Output indicator */
.output-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  margin-top: 2px;
  padding-top: 4px;
  border-top: 1px solid #313244;
}

.out-label {
  color: #9399b2;
  font-size: 10px;
}

.port-dot--out {
  /* same color as control */
}
</style>
