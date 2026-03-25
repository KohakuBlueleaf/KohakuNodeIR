<script setup>
import { ref, computed, provide } from "vue";
import { useEditorStore } from "../../stores/editor.js";
import { useGraphStore } from "../../stores/graph.js";
import { useDrag } from "../../composables/useDrag.js";
import { useResize } from "../../composables/useResize.js";
import ControlPort from "../ports/ControlPort.vue";
import { dtypeColor } from "../../utils/dtypeColors.js";

const CTRL_ROW_H = 18;
const HEADER_H = 32;
const DATA_ROW_H = 28;

const props = defineProps({
  node: { type: Object, required: true },
  headerColor: { type: String, default: null },
});

const editorStore = useEditorStore();
const graphStore = useGraphStore();
const nodeEl = ref(null);

function getZoom() {
  return editorStore.zoom ?? 1;
}

const { isDragging } = useDrag(props.node.id, nodeEl, getZoom);
const { isResizing } = useResize(props.node.id, nodeEl, getZoom);
const isSelected = computed(() =>
  editorStore.selectedNodeIds.has(props.node.id),
);

function onNodeClick(e) {
  if (isDragging.value || isResizing.value) return;
  editorStore.selectNode(props.node.id, e.ctrlKey || e.metaKey || e.shiftKey);
  e.stopPropagation();
}

const dataInputs = computed(() => props.node.dataPorts?.inputs ?? []);
const dataOutputs = computed(() => props.node.dataPorts?.outputs ?? []);
const ctrlInputs = computed(() => props.node.controlPorts?.inputs ?? []);
const ctrlOutputs = computed(() => props.node.controlPorts?.outputs ?? []);
const hasCtrlIn = computed(() => ctrlInputs.value.length > 0);
const hasCtrlOut = computed(() => ctrlOutputs.value.length > 0);

const dataRowCount = computed(() =>
  Math.max(dataInputs.value.length, dataOutputs.value.length),
);

function ctrlPortLeft(index, count) {
  if (count <= 1) return props.node.width / 2;
  const pad = 30;
  return pad + ((props.node.width - pad * 2) / (count - 1)) * index;
}

const draftWireType = computed(() => editorStore.draftWire?.portType ?? null);
provide("draftWireType", draftWireType);

function onPortMouseDown(nodeId, portId, portType) {
  editorStore.startDraftWire(nodeId, portId, portType);
}
function onPortMouseUp(nodeId, portId) {
  if (!editorStore.isDrawingWire) return;
  editorStore.endDraftWire(nodeId, portId);
}

// ── Inline editors for typed ports ──
function portIsConnected(portId) {
  return graphStore.getPortConnections(portId).length > 0;
}
function showEditor(port) {
  // Show inline editor if port has a known type and is not connected
  const editableTypes = ["int", "float", "str", "string", "bool"];
  if (portIsConnected(port.id)) return false;
  // Show if explicit editable type OR if port has a default value
  return (
    editableTypes.includes(port.dataType) || port.defaultValue !== undefined
  );
}
function onPortValueChange(port, e) {
  let val = e.target.value;
  if (port.dataType === "int") val = parseInt(val, 10) || 0;
  if (port.dataType === "float") val = parseFloat(val) || 0;
  // Store back on the port's defaultValue
  const liveNode = graphStore.nodes.get(props.node.id);
  const livePort = liveNode?.dataPorts.inputs.find((p) => p.id === port.id);
  if (livePort) livePort.defaultValue = val;
}
function onPortBoolChange(port, e) {
  const liveNode = graphStore.nodes.get(props.node.id);
  const livePort = liveNode?.dataPorts.inputs.find((p) => p.id === port.id);
  if (livePort) livePort.defaultValue = e.target.checked;
}

const TYPE_COLORS = {
  branch: "#fab387",
  merge: "#fab387",
  switch: "#fab387",
  parallel: "#fab387",
  value: "#a6e3a1",
  function: "#89b4fa",
};
const typeBadgeColor = computed(
  () => TYPE_COLORS[props.node.type] ?? "#89b4fa",
);

const nodeStyle = computed(() => ({
  left: `${props.node.x}px`,
  top: `${props.node.y}px`,
  width: `${props.node.width}px`,
  minHeight: `${(hasCtrlIn.value ? CTRL_ROW_H : 0) + HEADER_H + dataRowCount.value * DATA_ROW_H + (hasCtrlOut.value ? CTRL_ROW_H : 0) + 8}px`,
}));
</script>

<template>
  <div
    ref="nodeEl"
    class="node-root"
    :class="{
      'node-root--selected': isSelected,
      'node-root--dragging': isDragging,
    }"
    :style="nodeStyle"
    :data-node-id="node.id"
    @click.stop="onNodeClick"
  >
    <!-- Control inputs (top) -->
    <div v-if="hasCtrlIn && editorStore.showCtrlPorts" class="ctrl-row">
      <ControlPort
        v-for="(port, i) in ctrlInputs"
        :key="port.id"
        :port="port"
        :node-id="node.id"
        direction="input"
        :port-index="i"
        :total-ports="ctrlInputs.length"
        :style="{ left: ctrlPortLeft(i, ctrlInputs.length) + 'px' }"
        @port-mousedown="(p) => onPortMouseDown(p.nodeId, p.portId, p.portType)"
        @port-mouseup="(p) => onPortMouseUp(p.nodeId, p.portId)"
      />
    </div>

    <!-- Header -->
    <div
      class="node-header"
      :style="headerColor ? { background: headerColor } : {}"
    >
      <span class="node-badge" :style="{ background: typeBadgeColor }" />
      <span class="node-name">{{ node.name }}</span>
      <span class="node-type-tag">{{ node.type }}</span>
    </div>

    <!-- Data port rows -->
    <div v-if="dataRowCount > 0" class="data-rows">
      <div v-for="i in dataRowCount" :key="'dr-' + i" class="data-row">
        <!-- Left: input dot -->
        <div
          v-if="dataInputs[i - 1]"
          class="dp dp--in-dot"
          :data-port-id="dataInputs[i - 1].id"
          :data-node-id="node.id"
          data-port-type="data"
          data-port-dir="input"
          @mouseup.stop="onPortMouseUp(node.id, dataInputs[i - 1].id)"
        >
          <div
            class="dp__dot dp__dot--data"
            :style="{ background: dtypeColor(dataInputs[i - 1]?.dataType) }"
          />
        </div>
        <div v-else class="dp__dot-spacer" />

        <!-- Center: label + optional inline editor -->
        <div class="data-row__center">
          <!-- Input label -->
          <span v-if="dataInputs[i - 1]" class="dp__label dp__label--in">
            {{ dataInputs[i - 1].name }}
          </span>

          <!-- Inline editor for typed input ports (ComfyUI-style) -->
          <template v-if="dataInputs[i - 1] && showEditor(dataInputs[i - 1])">
            <label
              v-if="dataInputs[i - 1].dataType === 'bool'"
              class="dp__bool"
            >
              <input
                type="checkbox"
                :checked="!!dataInputs[i - 1].defaultValue"
                @change="onPortBoolChange(dataInputs[i - 1], $event)"
                @pointerdown.stop
                @click.stop
              />
            </label>
            <input
              v-else
              class="dp__input"
              :type="
                ['int', 'float'].includes(dataInputs[i - 1].dataType)
                  ? 'number'
                  : 'text'
              "
              :value="dataInputs[i - 1].defaultValue ?? ''"
              :placeholder="dataInputs[i - 1].dataType"
              @change="onPortValueChange(dataInputs[i - 1], $event)"
              @pointerdown.stop
              @click.stop
            />
          </template>

          <!-- Spacer between input and output labels -->
          <span class="data-row__spacer" />

          <!-- Output label -->
          <span v-if="dataOutputs[i - 1]" class="dp__label dp__label--out">
            {{ dataOutputs[i - 1].name }}
          </span>
        </div>

        <!-- Right: output dot -->
        <div
          v-if="dataOutputs[i - 1]"
          class="dp dp--out-dot"
          :data-port-id="dataOutputs[i - 1].id"
          :data-node-id="node.id"
          data-port-type="data"
          data-port-dir="output"
          @mousedown.stop.prevent="
            onPortMouseDown(node.id, dataOutputs[i - 1].id, 'data')
          "
        >
          <div
            class="dp__dot dp__dot--data"
            :style="{ background: dtypeColor(dataOutputs[i - 1]?.dataType) }"
          />
        </div>
        <div v-else class="dp__dot-spacer" />
      </div>
    </div>

    <!-- Body: type-specific content (buttons, etc.) -->
    <div class="node-body">
      <slot name="body" />
    </div>

    <!-- Control outputs (bottom) -->
    <div
      v-if="hasCtrlOut && editorStore.showCtrlPorts"
      class="ctrl-row ctrl-row--bot"
    >
      <ControlPort
        v-for="(port, i) in ctrlOutputs"
        :key="port.id"
        :port="port"
        :node-id="node.id"
        direction="output"
        :port-index="i"
        :total-ports="ctrlOutputs.length"
        :label="
          node.type === 'branch'
            ? port.name === 'true'
              ? 'T'
              : port.name === 'false'
                ? 'F'
                : null
            : null
        "
        :style="{ left: ctrlPortLeft(i, ctrlOutputs.length) + 'px' }"
        @port-mousedown="(p) => onPortMouseDown(p.nodeId, p.portId, p.portType)"
        @port-mouseup="(p) => onPortMouseUp(p.nodeId, p.portId)"
      />
    </div>
  </div>
</template>

<style scoped>
.node-root {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: #1e1e2e;
  border: 1.5px solid #45475a;
  border-radius: 8px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
  user-select: none;
  z-index: 10;
  overflow: visible;
  transition:
    border-color 0.12s,
    box-shadow 0.15s;
  box-sizing: border-box;
}
.node-root:hover {
  border-color: #6c8ebf;
}
.node-root--selected {
  border-color: #89b4fa;
  box-shadow:
    0 2px 6px rgba(0, 0, 0, 0.45),
    0 0 0 2px rgba(137, 180, 250, 0.3);
  z-index: 12;
}
.node-root--dragging {
  z-index: 50;
  opacity: 0.92;
}

.ctrl-row {
  position: relative;
  height: 18px;
  flex-shrink: 0;
  border-bottom: 1px solid #313244;
}
.ctrl-row--bot {
  border-bottom: none;
  border-top: 1px solid #313244;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 32px;
  background: #313244;
  border-bottom: 1px solid #45475a;
  cursor: grab;
  flex-shrink: 0;
}
.node-root--dragging .node-header {
  cursor: grabbing;
}
.node-badge {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  opacity: 0.85;
  flex-shrink: 0;
}
.node-name {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: #cdd6f4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.node-type-tag {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #6c7086;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
  flex-shrink: 0;
}

/* Data port rows */
.data-rows {
  flex-shrink: 0;
}
.data-row {
  display: flex;
  align-items: center;
  height: 28px;
}

.dp {
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: crosshair;
  flex-shrink: 0;
  /* Larger invisible hit area around the 10px dot */
  width: 20px;
  height: 24px;
}
.dp--in-dot {
  margin-left: -10px;
}
.dp--out-dot {
  margin-right: -10px;
}
.dp__dot-spacer {
  width: 10px;
  flex-shrink: 0;
}

.dp__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid #1e1e2e;
  flex-shrink: 0;
  transition:
    background 0.12s,
    box-shadow 0.12s;
}
.dp__dot--data {
  /* color set dynamically via inline style; fallback for any edge case */
  background: #9399b2;
}
.dp:hover .dp__dot {
  background: #b4d0ff;
  box-shadow: 0 0 6px 2px rgba(137, 180, 250, 0.55);
}

.data-row__center {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  padding: 0 4px;
  gap: 4px;
}
.data-row__spacer {
  flex: 1;
}

.dp__label {
  font-size: 10px;
  color: #a6adc8;
  white-space: nowrap;
  flex-shrink: 0;
}
.dp__label--in {
}
.dp__label--out {
  color: #89b4fa;
}

/* Inline editors */
.dp__input {
  width: 50px;
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid #45475a;
  background: #11111b;
  color: #cdd6f4;
  font-size: 10px;
  font-family: monospace;
  outline: none;
  flex-shrink: 1;
  min-width: 30px;
}
.dp__input:focus {
  border-color: #89b4fa;
}
.dp__bool {
  display: flex;
  align-items: center;
  cursor: pointer;
}
.dp__bool input {
  accent-color: #89b4fa;
  width: 12px;
  height: 12px;
  cursor: pointer;
}

.node-body {
  padding: 4px 10px;
  flex-shrink: 0;
}
</style>
