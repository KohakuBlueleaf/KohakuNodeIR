<script setup>
// ReporterBlock.vue — inline oval expression block for value/reporter nodes.
// Used inside input slots of statement and control blocks.
// Clicking on an editable slot opens an inline input to update the default value.

import { ref, nextTick } from "vue";
import { useGraphStore } from "../../stores/graph.js";
import { useHistoryStore } from "../../stores/history.js";

const props = defineProps({
  /** InputSlot object (from blockTree.js resolveInputSlots) */
  slot: {
    type: Object,
    required: true,
  },
});

// ── Stores ─────────────────────────────────────────────────────────────────────
const graph = useGraphStore();
const history = useHistoryStore();

// ── Editing state ─────────────────────────────────────────────────────────────
const isEditing = ref(false);
const editValue = ref("");
const inputRef = ref(null);

// ── Slot is editable if it is not connected to another node (use default) ─────
function isEditable(slot) {
  return !slot.connected || slot.literalValue !== null;
}

// ── Display text ──────────────────────────────────────────────────────────────
function slotLabel(slot) {
  if (!slot.connected) {
    const v = slot.literalValue;
    if (v === null || v === undefined) return `(${slot.portName})`;
    if (typeof v === "string") return `"${v}"`;
    return String(v);
  }
  // Connected to a non-value node → show variable / node name
  if (slot.literalValue !== null && slot.literalValue !== undefined) {
    // Connected value node — show the literal
    const v = slot.literalValue;
    if (typeof v === "string") return `"${v}"`;
    return String(v);
  }
  return slot.sourceNodeName ?? slot.portName;
}

// ── Data type → accent color ──────────────────────────────────────────────────
const TYPE_COLORS = {
  bool: "#f38ba8",
  int: "#89b4fa",
  float: "#89dceb",
  str: "#a6e3a1",
  any: "#a6adc8",
};

function accentColor(slot) {
  return TYPE_COLORS[slot.dataType] ?? TYPE_COLORS.any;
}

// ── Edit interaction ──────────────────────────────────────────────────────────

function startEdit(e) {
  if (!isEditable(props.slot)) return;
  // If this slot is connected to a value node, edit that node's value
  if (props.slot.connected && props.slot.sourceNodeId) {
    const srcNode = graph.nodes.get(props.slot.sourceNodeId);
    if (!srcNode) return;
    const current =
      srcNode.properties?.value ??
      srcNode.dataPorts?.outputs?.[0]?.defaultValue ??
      "";
    editValue.value = String(current);
  } else {
    // Unconnected slot — edit the port's defaultValue
    editValue.value =
      props.slot.literalValue !== null && props.slot.literalValue !== undefined
        ? String(props.slot.literalValue)
        : "";
  }

  isEditing.value = true;
  nextTick(() => {
    if (inputRef.value) {
      inputRef.value.select();
      inputRef.value.focus();
    }
  });

  e.stopPropagation();
}

function commitEdit() {
  if (!isEditing.value) return;
  isEditing.value = false;

  const raw = editValue.value;

  if (props.slot.connected && props.slot.sourceNodeId) {
    // Update the source value node
    const srcNode = graph.nodes.get(props.slot.sourceNodeId);
    if (!srcNode) return;
    history.pushState();
    const parsed = parseValue(raw, props.slot.dataType);
    if (srcNode.properties !== undefined) {
      srcNode.properties.value = parsed;
    }
    const outPort = srcNode.dataPorts?.outputs?.[0];
    if (outPort) outPort.defaultValue = parsed;
  } else {
    // Update the port's defaultValue on the parent node
    // We need to find the node that owns this port
    const nodeId = findNodeForInputPort(props.slot.portId);
    if (!nodeId) return;
    const node = graph.nodes.get(nodeId);
    if (!node) return;
    history.pushState();
    const parsed = parseValue(raw, props.slot.dataType);
    const port = node.dataPorts.inputs.find((p) => p.id === props.slot.portId);
    if (port) port.defaultValue = parsed;
  }
}

function cancelEdit() {
  isEditing.value = false;
}

function onKeyDown(e) {
  if (e.key === "Enter") {
    e.preventDefault();
    commitEdit();
  } else if (e.key === "Escape") {
    cancelEdit();
  }
  e.stopPropagation();
}

/** Toggle boolean value with a single click (no text input needed). */
function toggleBool() {
  if (!isEditable(props.slot)) return;

  if (props.slot.connected && props.slot.sourceNodeId) {
    const srcNode = graph.nodes.get(props.slot.sourceNodeId);
    if (!srcNode) return;
    history.pushState();
    const current =
      srcNode.properties?.value ??
      srcNode.dataPorts?.outputs?.[0]?.defaultValue ??
      false;
    const next = !current;
    if (srcNode.properties !== undefined) srcNode.properties.value = next;
    const outPort = srcNode.dataPorts?.outputs?.[0];
    if (outPort) outPort.defaultValue = next;
  } else {
    const nodeId = findNodeForInputPort(props.slot.portId);
    if (!nodeId) return;
    const node = graph.nodes.get(nodeId);
    if (!node) return;
    history.pushState();
    const port = node.dataPorts.inputs.find((p) => p.id === props.slot.portId);
    if (port) port.defaultValue = !port.defaultValue;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseValue(raw, dataType) {
  switch (dataType) {
    case "bool":
      return raw === "true" || raw === "1";
    case "int":
      return parseInt(raw, 10) || 0;
    case "float":
      return parseFloat(raw) || 0;
    default:
      return raw;
  }
}

function findNodeForInputPort(portId) {
  for (const node of graph.nodes.values()) {
    if (node.dataPorts.inputs.some((p) => p.id === portId)) return node.id;
  }
  return null;
}

function inputType(dataType) {
  if (dataType === "int" || dataType === "float") return "number";
  return "text";
}
</script>

<template>
  <!-- Boolean slot: click to toggle -->
  <span
    v-if="slot.dataType === 'bool' && isEditable(slot)"
    class="reporter-block reporter-block--bool"
    :style="{ '--accent': accentColor(slot) }"
    :title="slot.portName + ' : bool (click to toggle)'"
    role="button"
    tabindex="0"
    @click.stop="toggleBool"
    @keydown.enter.stop="toggleBool"
  >
    <span
      class="reporter-bool-indicator"
      :class="{
        'is-true':
          slot.literalValue === true ||
          (slot.connected && slot.literalValue === true),
      }"
    />
    <span class="reporter-label">{{
      slot.literalValue === true ? "true" : "false"
    }}</span>
  </span>

  <!-- Editable slot: click to open inline input -->
  <span
    v-else-if="isEditable(slot) && slot.dataType !== 'bool'"
    class="reporter-block reporter-block--editable"
    :style="{ '--accent': accentColor(slot) }"
    :title="slot.portName + ' : ' + slot.dataType"
    role="button"
    tabindex="0"
    @click.stop="startEdit"
    @keydown.enter.stop="startEdit"
  >
    <template v-if="!isEditing">
      <span
        v-if="slot.connected && slot.literalValue === null"
        class="reporter-dot"
      />
      <span class="reporter-label">{{ slotLabel(slot) }}</span>
    </template>
    <template v-else>
      <input
        ref="inputRef"
        v-model="editValue"
        class="reporter-input"
        :type="inputType(slot.dataType)"
        :step="slot.dataType === 'float' ? 'any' : undefined"
        @blur="commitEdit"
        @keydown="onKeyDown"
        @click.stop
      />
    </template>
  </span>

  <!-- Read-only (connected non-literal) -->
  <span
    v-else
    class="reporter-block"
    :style="{ '--accent': accentColor(slot) }"
    :title="slot.portName + ' : ' + slot.dataType"
  >
    <span
      v-if="slot.connected && slot.literalValue === null"
      class="reporter-dot"
    />
    <span class="reporter-label">{{ slotLabel(slot) }}</span>
  </span>
</template>

<style scoped>
.reporter-block {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  background: color-mix(in srgb, var(--accent) 18%, #1e1e2e);
  border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
  border-radius: 999px;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 11px;
  color: var(--accent);
  white-space: nowrap;
  vertical-align: middle;
  line-height: 1.4;
  cursor: default;
  user-select: none;
}

.reporter-block--editable {
  cursor: text;
}

.reporter-block--editable:hover {
  background: color-mix(in srgb, var(--accent) 26%, #1e1e2e);
  border-color: color-mix(in srgb, var(--accent) 75%, transparent);
}

.reporter-block--bool {
  cursor: pointer;
}

.reporter-block--bool:hover {
  background: color-mix(in srgb, var(--accent) 26%, #1e1e2e);
}

/* Colored dot for variable references (non-literal connections) */
.reporter-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}

.reporter-label {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Bool toggle indicator */
.reporter-bool-indicator {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--accent) 35%, transparent);
  border: 1.5px solid var(--accent);
  flex-shrink: 0;
  transition: background 0.1s;
}

.reporter-bool-indicator.is-true {
  background: var(--accent);
}

/* Inline text/number input */
.reporter-input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--accent);
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 11px;
  width: 80px;
  min-width: 40px;
  padding: 0;
  line-height: 1.4;
}

/* Remove number input spinners */
.reporter-input[type="number"]::-webkit-inner-spin-button,
.reporter-input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
}
.reporter-input[type="number"] {
  -moz-appearance: textfield;
}
</style>
