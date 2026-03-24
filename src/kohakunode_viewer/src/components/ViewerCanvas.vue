<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { dataWirePath, controlWirePath } from "../utils/bezier.js";
import ViewNode from "./ViewNode.vue";

// ── Props ─────────────────────────────────────────────────────────────────────
const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
});

// ── Container ref ─────────────────────────────────────────────────────────────
const containerRef = ref(null);

// ── Pan state ─────────────────────────────────────────────────────────────────
const panX = ref(0);
const panY = ref(0);
const zoom = ref(1);

const isPanning = ref(false);
let panStartX = 0;
let panStartY = 0;
let panOriginX = 0;
let panOriginY = 0;

function beginPan(clientX, clientY) {
  isPanning.value = true;
  panStartX = clientX;
  panStartY = clientY;
  panOriginX = panX.value;
  panOriginY = panY.value;
}

function continuePan(clientX, clientY) {
  if (!isPanning.value) return;
  panX.value = panOriginX + (clientX - panStartX);
  panY.value = panOriginY + (clientY - panStartY);
}

function endPan() {
  isPanning.value = false;
}

// ── Zoom ──────────────────────────────────────────────────────────────────────
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;
const ZOOM_SPEED = 0.001;

function onWheel(e) {
  e.preventDefault();
  const rect = containerRef.value.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  const oldZoom = zoom.value;
  const delta = -e.deltaY * ZOOM_SPEED;
  const newZoom = Math.min(
    ZOOM_MAX,
    Math.max(ZOOM_MIN, +(oldZoom + delta * oldZoom).toFixed(4))
  );

  // Zoom toward cursor: keep world point under cursor fixed
  panX.value = mx - ((mx - panX.value) / oldZoom) * newZoom;
  panY.value = my - ((my - panY.value) / oldZoom) * newZoom;
  zoom.value = newZoom;
}

// ── Transform / grid styles ───────────────────────────────────────────────────
const GRID_SIZE = 20;

const transformStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
  transformOrigin: "0 0",
}));

const gridStyle = computed(() => {
  const gridPx = GRID_SIZE * zoom.value;
  const ox = ((panX.value % gridPx) + gridPx) % gridPx;
  const oy = ((panY.value % gridPx) + gridPx) % gridPx;
  return {
    backgroundImage: "radial-gradient(circle, #2a2a3e 1px, transparent 1px)",
    backgroundSize: `${gridPx}px ${gridPx}px`,
    backgroundPosition: `${ox}px ${oy}px`,
  };
});

const cursorStyle = computed(() => (isPanning.value ? "grabbing" : "grab"));

// ── Port position (mirrors graph store logic, prop-driven) ────────────────────
const PORT_PADDING = 30;
const HEADER_H = 32;
const CTRL_ROW_H = 18;
const DATA_ROW_H = 28;

function evenSpacing(index, count, span) {
  if (count === 1) return span / 2;
  return PORT_PADDING + index * ((span - PORT_PADDING * 2) / (count - 1));
}

function getPortPosition(nodeId, portName) {
  const node = props.nodes.find((n) => n.id === nodeId);
  if (!node) return null;

  const { x, y, width, height } = node;
  const dataInputs = node.dataInputs || [];
  const dataOutputs = node.dataOutputs || [];
  const ctrlInputs = node.ctrlInputs || [];
  const ctrlOutputs = node.ctrlOutputs || [];
  const hasCtrlIn = ctrlInputs.length > 0;

  // ALWAYS auto-calculate height from port count (stored height may be wrong)
  const dataRows = Math.max(dataInputs.length, dataOutputs.length);
  const nodeH = Math.max(
    height || 0,
    (hasCtrlIn ? CTRL_ROW_H : 0) + HEADER_H + dataRows * DATA_ROW_H +
    (ctrlOutputs.length > 0 ? CTRL_ROW_H : 0) + 16
  );
  const nodeW = width || 180;

  function dataRowY(index) {
    return (hasCtrlIn ? CTRL_ROW_H : 0) + HEADER_H + index * DATA_ROW_H + DATA_ROW_H / 2;
  }

  // Data inputs — match by port name
  const dataInIndex = dataInputs.findIndex((p) => p.name === portName);
  if (dataInIndex !== -1) return { x, y: y + dataRowY(dataInIndex) };

  // Data outputs
  const dataOutIndex = dataOutputs.findIndex((p) => p.name === portName);
  if (dataOutIndex !== -1) return { x: x + nodeW, y: y + dataRowY(dataOutIndex) };

  // Control inputs
  const ctrlInIndex = ctrlInputs.indexOf(portName);
  if (ctrlInIndex !== -1) {
    return { x: x + evenSpacing(ctrlInIndex, ctrlInputs.length, nodeW), y };
  }

  // Control outputs
  const ctrlOutIndex = ctrlOutputs.indexOf(portName);
  if (ctrlOutIndex !== -1) {
    return { x: x + evenSpacing(ctrlOutIndex, ctrlOutputs.length, nodeW), y: y + nodeH };
  }

  return null;
}

// ── Wire descriptors ──────────────────────────────────────────────────────────
const wires = computed(() => {
  const result = [];
  for (let i = 0; i < props.edges.length; i++) {
    const edge = props.edges[i];
    const from = getPortPosition(edge.fromNode, edge.fromPort);
    const to = getPortPosition(edge.toNode, edge.toPort);
    if (!from || !to) continue;

    const isCtrl = edge.type === "control";
    const d = isCtrl
      ? controlWirePath(from.x, from.y, to.x, to.y)
      : dataWirePath(from.x, from.y, to.x, to.y);

    result.push({ id: `e${i}`, d, edgeType: isCtrl ? "control" : "data" });
  }
  return result;
});

// ── Pointer handlers — pan only, no editing ───────────────────────────────────
function onPointerDown(e) {
  // Pan on left-click anywhere on the background / canvas-transform
  if (e.button === 0) {
    const isBackground =
      e.target === containerRef.value ||
      e.target.classList.contains("canvas-transform");
    if (isBackground) {
      e.preventDefault();
      beginPan(e.clientX, e.clientY);
    }
  }
  // Middle-click always pans
  if (e.button === 1) {
    e.preventDefault();
    beginPan(e.clientX, e.clientY);
  }
}

function onPointerMove(e) {
  continuePan(e.clientX, e.clientY);
}

function onPointerUp() {
  endPan();
}

function onContextMenu(e) {
  e.preventDefault();
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  containerRef.value?.addEventListener("wheel", onWheel, { passive: false });
});

onBeforeUnmount(() => {
  containerRef.value?.removeEventListener("wheel", onWheel);
});
</script>

<template>
  <div
    ref="containerRef"
    class="canvas-container"
    :style="[gridStyle, { cursor: cursorStyle }]"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointerleave="onPointerUp"
    @contextmenu="onContextMenu"
  >
    <div class="canvas-transform" :style="transformStyle">
      <!-- Wire SVG layer — behind nodes -->
      <svg class="wire-layer" overflow="visible">
        <path
          v-for="wire in wires"
          :key="wire.id"
          :d="wire.d"
          :class="['wire', wire.edgeType === 'control' ? 'wire-control' : 'wire-data']"
          fill="none"
        />
      </svg>

      <!-- Nodes -->
      <ViewNode
        v-for="node in props.nodes"
        :key="node.id"
        :node="node"
      />
    </div>

    <!-- Empty state -->
    <div v-if="props.nodes.length === 0" class="empty-state">
      <div class="empty-state__icon">⬡</div>
      <div class="empty-state__text">No graph loaded</div>
      <div class="empty-state__hint">Drop a file or use the toolbar</div>
    </div>
  </div>
</template>

<style scoped>
.canvas-container {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background-color: #11111b;
  user-select: none;
  -webkit-user-select: none;
}

.canvas-transform {
  position: absolute;
  top: 0;
  left: 0;
  width: 4000px;
  height: 4000px;
}

/* ── Wire layer ── */
.wire-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}

.wire-data {
  stroke: #89b4fa;
  stroke-width: 2;
  stroke-linecap: round;
  opacity: 0.85;
}

.wire-control {
  stroke: #fab387;
  stroke-width: 3;
  stroke-linecap: round;
  opacity: 0.85;
}

/* ── Empty state ── */
.empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  pointer-events: none;
}

.empty-state__icon {
  font-size: 48px;
  opacity: 0.15;
  line-height: 1;
}

.empty-state__text {
  font-size: 16px;
  color: #45475a;
  font-weight: 600;
}

.empty-state__hint {
  font-size: 12px;
  color: #313244;
}
</style>
