<script setup>
/**
 * FunctionNode — body content for 'function' type nodes.
 * Rendered inside BaseNode's #body slot via NodeRenderer.
 *
 * Responsibilities:
 *   - Displays data input ports with their type labels
 *   - Displays data output ports
 *   - Shows a "has code" badge when node.properties.code is set
 *   - Renders an inline editable default-value field for ports that have a defaultValue
 * Emits:
 *   - update:property  { key: string, value: any }  — when an inline field changes
 */

const props = defineProps({
  node: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(['update:property']);

// ---- helpers ----

/** Friendly colour label for a dataType string */
const TYPE_COLORS = {
  int:    '#89b4fa', // blue
  float:  '#89dceb', // cyan
  string: '#a6e3a1', // green
  bool:   '#fab387', // peach
  any:    '#9399b2', // subtext
  none:   '#6c7086', // muted
};

function typeColor(dataType) {
  return TYPE_COLORS[dataType] ?? TYPE_COLORS.any;
}

function handleDefaultChange(port, event) {
  // Persist the new default value back onto the port definition
  port.defaultValue = event.target.value;
  emit('update:property', { key: `port.${port.id}.defaultValue`, value: event.target.value });
}
</script>

<template>
  <div class="fn-body">

    <!-- "Has code" badge -->
    <div v-if="node.properties?.code" class="code-badge">
      <span class="code-dot" />
      <span>has code</span>
    </div>

    <!-- Data inputs -->
    <div
      v-if="node.dataPorts?.inputs?.length"
      class="port-section"
    >
      <div
        v-for="port in node.dataPorts.inputs"
        :key="port.id"
        class="port-row port-row--in"
      >
        <span
          class="port-type-dot"
          :style="{ background: typeColor(port.dataType) }"
        />
        <span class="port-name">{{ port.name }}</span>
        <span
          v-if="port.dataType"
          class="port-type-label"
          :style="{ color: typeColor(port.dataType) }"
        >{{ port.dataType }}</span>
        <!-- Inline editable default value -->
        <input
          v-if="port.defaultValue !== undefined && port.defaultValue !== null"
          class="default-input"
          :value="String(port.defaultValue)"
          @change="handleDefaultChange(port, $event)"
          @pointerdown.stop
          @click.stop
        />
      </div>
    </div>

    <!-- Divider when both sections are present -->
    <div
      v-if="node.dataPorts?.inputs?.length && node.dataPorts?.outputs?.length"
      class="divider"
    />

    <!-- Data outputs -->
    <div
      v-if="node.dataPorts?.outputs?.length"
      class="port-section"
    >
      <div
        v-for="port in node.dataPorts.outputs"
        :key="port.id"
        class="port-row port-row--out"
      >
        <span class="port-name">{{ port.name }}</span>
        <span
          v-if="port.dataType"
          class="port-type-label"
          :style="{ color: typeColor(port.dataType) }"
        >{{ port.dataType }}</span>
        <span
          class="port-type-dot"
          :style="{ background: typeColor(port.dataType) }"
        />
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="!node.dataPorts?.inputs?.length && !node.dataPorts?.outputs?.length"
      class="empty-hint"
    >
      no data ports
    </div>

  </div>
</template>

<style scoped>
.fn-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
}

/* Has-code badge */
.code-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(137, 180, 250, 0.12);
  border: 1px solid rgba(137, 180, 250, 0.25);
  color: #89b4fa;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
  width: fit-content;
}
.code-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #89b4fa;
  flex-shrink: 0;
}

/* Port sections */
.port-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.port-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 18px;
  padding: 1px 0;
}

.port-row--in {
  /* inputs left-aligned — dot on the left */
  flex-direction: row;
}
.port-row--out {
  /* outputs right-aligned — dot on the right */
  flex-direction: row-reverse;
  text-align: right;
}

.port-type-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.port-name {
  flex: 1;
  color: #cdd6f4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.port-type-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: lowercase;
  white-space: nowrap;
  flex-shrink: 0;
}

/* Inline default value input */
.default-input {
  width: 52px;
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid #45475a;
  background: #11111b;
  color: #cdd6f4;
  font-size: 10px;
  font-family: monospace;
  outline: none;
  flex-shrink: 0;
}
.default-input:focus {
  border-color: #89b4fa;
}

.divider {
  height: 1px;
  background: #313244;
  margin: 3px 0;
}

.empty-hint {
  font-size: 10px;
  color: #45475a;
  font-style: italic;
  text-align: center;
  padding: 4px 0;
}
</style>
