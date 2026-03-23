<script setup>
/**
 * SwitchNode — body content for 'switch' type nodes.
 * Rendered inside BaseNode's #body slot via NodeRenderer.
 *
 * Layout:
 *   - Value data-input label
 *   - List of case outputs with their labels ("case 0", "case 1", …, "default")
 *   - Buttons to add / remove cases
 *
 * Header color (#2d2040) is applied by NodeRenderer via BaseNode's headerColor prop.
 *
 * Emits:
 *   - add-case     — request a new case control-output port
 *   - remove-case  { portId: string } — request removal of a case port
 */

import { computed } from 'vue';

const props = defineProps({
  node: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(['add-case', 'remove-case']);

const valuePort = computed(() => props.node.dataPorts?.inputs?.[0] ?? null);
const caseOutputs = computed(() => props.node.controlPorts?.outputs ?? []);
</script>

<template>
  <div class="switch-body">

    <!-- Value input -->
    <div class="value-row">
      <span class="port-dot port-dot--data" />
      <span class="label">{{ valuePort?.name ?? 'value' }}</span>
      <span class="type-tag">{{ valuePort?.dataType ?? 'any' }}</span>
    </div>

    <div class="divider" />

    <!-- Case outputs -->
    <div class="cases-list">
      <div
        v-for="(port, index) in caseOutputs"
        :key="port.id"
        class="case-row"
      >
        <span class="case-label">{{ port.name }}</span>
        <button
          class="remove-btn"
          title="Remove case"
          @click.stop="emit('remove-case', { portId: port.id })"
          @pointerdown.stop
        >×</button>
        <span class="port-dot port-dot--ctrl" />
      </div>
    </div>

    <!-- Add case button -->
    <button
      class="add-btn"
      title="Add case"
      @click.stop="emit('add-case')"
      @pointerdown.stop
    >
      <span class="add-icon">+</span>
      <span>add case</span>
    </button>

  </div>
</template>

<style scoped>
.switch-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
}

/* Value row */
.value-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 0;
}

.port-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.port-dot--data { background: #89b4fa; }
.port-dot--ctrl { background: #fab387; }

.label {
  flex: 1;
  color: #cdd6f4;
}

.type-tag {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #89b4fa;
}

.divider {
  height: 1px;
  background: #313244;
  margin: 2px 0;
}

/* Cases list */
.cases-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.case-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.case-label {
  flex: 1;
  color: #bac2de;
  font-size: 10px;
  font-family: monospace;
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
  border-color: #cba6f7;
  color: #cba6f7;
}
.add-icon {
  font-size: 13px;
  line-height: 1;
  font-weight: 700;
}
</style>
