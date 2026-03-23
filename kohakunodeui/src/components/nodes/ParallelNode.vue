<script setup>
/**
 * ParallelNode — body content for 'parallel' type nodes.
 * Rendered inside BaseNode's #body slot via NodeRenderer.
 *
 * Layout:
 *   - Single control input indicator at the top
 *   - List of parallel control outputs ("out 0", "out 1", …)
 *   - Buttons to add / remove parallel branches
 *
 * Header color (#1e3d2f) is applied by NodeRenderer via BaseNode's headerColor prop.
 *
 * Emits:
 *   - add-branch     — request a new control-output port
 *   - remove-branch  { portId: string } — request removal of a branch port
 */

import { computed } from 'vue';

const props = defineProps({
  node: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(['add-branch', 'remove-branch']);

const outputPorts = computed(() => props.node.controlPorts?.outputs ?? []);
</script>

<template>
  <div class="parallel-body">

    <!-- Single control input indicator -->
    <div class="in-row">
      <span class="port-dot" />
      <span class="label">in</span>
    </div>

    <div class="divider" />

    <!-- Output branches -->
    <div class="branches-list">
      <div
        v-for="port in outputPorts"
        :key="port.id"
        class="branch-row"
      >
        <span class="branch-label">{{ port.name }}</span>
        <button
          class="remove-btn"
          title="Remove branch"
          @click.stop="emit('remove-branch', { portId: port.id })"
          @pointerdown.stop
        >×</button>
        <span class="port-dot" />
      </div>
    </div>

    <!-- Add branch button -->
    <button
      class="add-btn"
      title="Add parallel branch"
      @click.stop="emit('add-branch')"
      @pointerdown.stop
    >
      <span class="add-icon">+</span>
      <span>add branch</span>
    </button>

  </div>
</template>

<style scoped>
.parallel-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
}

/* Control input row */
.in-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 0;
}

.port-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #fab387; /* --port-control */
  flex-shrink: 0;
}

.label {
  color: #cdd6f4;
}

.divider {
  height: 1px;
  background: #313244;
  margin: 2px 0;
}

/* Branches list */
.branches-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.branch-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.branch-label {
  flex: 1;
  color: #bac2de;
  font-size: 10px;
}

.remove-btn {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  border: 1px solid #45475a;
  background: transparent;
  color: #6c7086;
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: border-color 0.12s, color 0.12s;
}
.remove-btn:hover {
  border-color: #f38ba8;
  color: #f38ba8;
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
  border-color: #a6e3a1;
  color: #a6e3a1;
}
.add-icon {
  font-size: 13px;
  line-height: 1;
  font-weight: 700;
}
</style>
