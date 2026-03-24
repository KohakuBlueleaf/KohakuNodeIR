<script setup>
import { computed } from "vue";

// ── Layout constants (mirror graph store / BaseNode) ──────────────────────────
const CTRL_ROW_H = 18;
const HEADER_H = 32;
const DATA_ROW_H = 28;

const props = defineProps({
  /**
   * Node object shape (from parser output):
   * {
   *   id: string,
   *   type: string,       // 'function' | 'branch' | 'switch' | 'parallel' | 'value' | 'merge' | ...
   *   name: string,
   *   x: number, y: number,
   *   width: number, height: number,
   *   dataPorts:    { inputs: [{id, name, dataType, defaultValue?}], outputs: [{id, name, dataType}] },
   *   controlPorts: { inputs: [{id, name}], outputs: [{id, name}] },
   *   properties: {},
   * }
   */
  node: { type: Object, required: true },
  /**
   * Set of port IDs that have an incoming wire — used to suppress default
   * value display when the port is already driven.
   */
  connectedPortIds: { type: Object, default: () => new Set() },
});

// ── Port accessors ────────────────────────────────────────────────────────────
const dataInputs = computed(() => props.node.dataPorts?.inputs ?? []);
const dataOutputs = computed(() => props.node.dataPorts?.outputs ?? []);
const ctrlInputs = computed(() => props.node.controlPorts?.inputs ?? []);
const ctrlOutputs = computed(() => props.node.controlPorts?.outputs ?? []);
const hasCtrlIn = computed(() => ctrlInputs.value.length > 0);
const hasCtrlOut = computed(() => ctrlOutputs.value.length > 0);
const dataRowCount = computed(() =>
  Math.max(dataInputs.value.length, dataOutputs.value.length, 0)
);

// ── Type → header background color ───────────────────────────────────────────
const HEADER_COLORS = {
  branch: "#3d2f1e",
  switch: "#2d2040",
  parallel: "#1e3d2f",
  value: "#1e3d1e",
  merge: "#3d2f1e",
};

// ── Type → badge color (mirrors BaseNode) ─────────────────────────────────────
const BADGE_COLORS = {
  branch: "#fab387",
  merge: "#fab387",
  switch: "#fab387",
  parallel: "#fab387",
  value: "#a6e3a1",
  function: "#89b4fa",
  namespace: "#cba6f7",
  load: "#a6e3a1",
};

const headerBg = computed(() => HEADER_COLORS[props.node.type] ?? "#313244");
const badgeColor = computed(() => BADGE_COLORS[props.node.type] ?? "#89b4fa");

// ── Node dimensions ───────────────────────────────────────────────────────────
const nodeWidth = computed(() => props.node.width || 180);
const autoHeight = computed(
  () =>
    (hasCtrlIn.value ? CTRL_ROW_H : 0) +
    HEADER_H +
    Math.max(dataRowCount.value, 0) * DATA_ROW_H +
    (hasCtrlOut.value ? CTRL_ROW_H : 0) +
    8
);

const nodeStyle = computed(() => ({
  left: `${props.node.x ?? 0}px`,
  top: `${props.node.y ?? 0}px`,
  width: `${nodeWidth.value}px`,
  minHeight: `${autoHeight.value}px`,
}));

// ── Ctrl port horizontal positioning (mirrors BaseNode.ctrlPortLeft) ──────────
function ctrlPortLeft(index, count) {
  if (count <= 1) return nodeWidth.value / 2;
  const pad = 30;
  return pad + ((nodeWidth.value - pad * 2) / (count - 1)) * index;
}

// ── Default value display helper ──────────────────────────────────────────────
function defaultDisplay(port) {
  if (port.defaultValue === undefined || port.defaultValue === null) return null;
  if (props.connectedPortIds.has(port.id)) return null;
  return String(port.defaultValue);
}
</script>

<template>
  <div class="vnode" :style="nodeStyle" :data-node-id="node.id">
    <!-- ── Control inputs row (top) ── -->
    <div v-if="hasCtrlIn" class="ctrl-row ctrl-row--top">
      <div
        v-for="(port, i) in ctrlInputs"
        :key="port.id"
        class="ctrl-port ctrl-port--in"
        :style="{ left: ctrlPortLeft(i, ctrlInputs.length) + 'px' }"
        :title="port.name"
      >
        <div class="ctrl-diamond" />
        <span class="ctrl-label ctrl-label--in">{{ port.name }}</span>
      </div>
    </div>

    <!-- ── Header ── -->
    <div class="vnode-header" :style="{ background: headerBg }">
      <span class="vnode-badge" :style="{ background: badgeColor }" />
      <span class="vnode-name">{{ node.name }}</span>
      <span class="vnode-type-tag">{{ node.type }}</span>
    </div>

    <!-- ── Data port rows ── -->
    <div v-if="dataRowCount > 0" class="data-rows">
      <div v-for="i in dataRowCount" :key="'dr-' + i" class="data-row">
        <!-- Left: input dot -->
        <div
          v-if="dataInputs[i - 1]"
          class="dp dp--in"
          :data-port-id="dataInputs[i - 1].id"
          :data-node-id="node.id"
          data-port-type="data"
          data-port-dir="input"
        >
          <div class="dp__dot dp__dot--data" />
        </div>
        <div v-else class="dp__spacer" />

        <!-- Center: labels + optional default value -->
        <div class="data-row__center">
          <span v-if="dataInputs[i - 1]" class="dp__label dp__label--in">
            {{ dataInputs[i - 1].name }}
          </span>
          <span
            v-if="dataInputs[i - 1] && defaultDisplay(dataInputs[i - 1]) !== null"
            class="dp__default"
          >= {{ defaultDisplay(dataInputs[i - 1]) }}</span>
          <span class="data-row__spacer" />
          <span v-if="dataOutputs[i - 1]" class="dp__label dp__label--out">
            {{ dataOutputs[i - 1].name }}
          </span>
        </div>

        <!-- Right: output dot -->
        <div
          v-if="dataOutputs[i - 1]"
          class="dp dp--out"
          :data-port-id="dataOutputs[i - 1].id"
          :data-node-id="node.id"
          data-port-type="data"
          data-port-dir="output"
        >
          <div class="dp__dot dp__dot--data" />
        </div>
        <div v-else class="dp__spacer" />
      </div>
    </div>

    <!-- ── Control outputs row (bottom) ── -->
    <div v-if="hasCtrlOut" class="ctrl-row ctrl-row--bot">
      <div
        v-for="(port, i) in ctrlOutputs"
        :key="port.id"
        class="ctrl-port ctrl-port--out"
        :style="{ left: ctrlPortLeft(i, ctrlOutputs.length) + 'px' }"
        :title="port.name"
      >
        <span class="ctrl-label ctrl-label--out">{{ port.name }}</span>
        <div class="ctrl-diamond" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── Node root ── */
.vnode {
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
  box-sizing: border-box;
  pointer-events: none; /* read-only: no drag/click interaction */
}

/* ── Control rows ── */
.ctrl-row {
  position: relative;
  height: 18px;
  flex-shrink: 0;
}
.ctrl-row--top {
  border-bottom: 1px solid #313244;
}
.ctrl-row--bot {
  border-top: 1px solid #313244;
}

/* Individual control port, absolutely positioned within ctrl-row */
.ctrl-port {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.ctrl-port--in {
  top: 0;
  transform: translateX(-50%) translateY(-50%);
}
.ctrl-port--out {
  bottom: 0;
  transform: translateX(-50%) translateY(50%);
}

.ctrl-diamond {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  background: #fab387;
  border: 1.5px solid #1e1e2e;
  transform: rotate(45deg);
}

.ctrl-label {
  font-size: 8px;
  color: #a6adc8;
  white-space: nowrap;
  line-height: 1;
  margin: 2px 0;
}
.ctrl-label--in {
  order: 1; /* label below diamond for inputs */
}
.ctrl-label--out {
  order: -1; /* label above diamond for outputs */
}

/* ── Header ── */
.vnode-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 32px;
  background: #313244;
  border-bottom: 1px solid #45475a;
  flex-shrink: 0;
}
.vnode-badge {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  opacity: 0.85;
  flex-shrink: 0;
}
.vnode-name {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: #cdd6f4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.vnode-type-tag {
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

/* ── Data port rows ── */
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
  flex-shrink: 0;
  width: 20px;
  height: 24px;
}
.dp--in {
  margin-left: -10px;
}
.dp--out {
  margin-right: -10px;
}
.dp__spacer {
  width: 10px;
  flex-shrink: 0;
}
.dp__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid #1e1e2e;
  flex-shrink: 0;
}
.dp__dot--data {
  background: #89b4fa;
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
.dp__label--out {
  color: #89b4fa;
}

.dp__default {
  font-size: 9px;
  color: #6c7086;
  font-family: monospace;
  white-space: nowrap;
  flex-shrink: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
