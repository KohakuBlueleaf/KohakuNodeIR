<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { useGraphStore } from '../../stores/graph.js';
import { useEditorStore } from '../../stores/editor.js';
import { useNodeRegistryStore } from '../../stores/nodeRegistry.js';
import { GRID_SIZE, snapToGrid } from '../../utils/grid.js';
import WireLayer  from '../wire/WireLayer.vue';
import DraftWire  from '../wire/DraftWire.vue';
import NodeRenderer from '../nodes/NodeRenderer.vue';
import SelectionBox from './SelectionBox.vue';

// ── Props / emits ──────────────────────────────────────────────────────────────
const props = defineProps({
  /** Controlled zoom level from the parent toolbar. */
  zoom: {
    type: Number,
    default: 1,
  },
});
const emit = defineEmits(['update:zoom']);

// ── Store ──────────────────────────────────────────────────────────────────────
const graph = useGraphStore();
const editor = useEditorStore();
const registry = useNodeRegistryStore();

// ── Refs ───────────────────────────────────────────────────────────────────────
const containerRef = ref(null);

// ── Pan state ─────────────────────────────────────────────────────────────────
const panX = ref(0);
const panY = ref(0);

// ── Panning (middle-mouse or space+drag) ──────────────────────────────────────
const isPanning    = ref(false);
const spaceHeld    = ref(false);
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
const ZOOM_MIN  = 0.1;
const ZOOM_MAX  = 4;
const ZOOM_SPEED = 0.001;

function onWheel(e) {
  e.preventDefault();

  const rect = containerRef.value.getBoundingClientRect();
  // Mouse position relative to canvas container
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  const oldZoom = props.zoom;
  const delta   = -e.deltaY * ZOOM_SPEED;
  const newZoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, +(oldZoom + delta * oldZoom).toFixed(4)));

  // Zoom toward the mouse pointer: adjust pan so the world point under the
  // cursor stays fixed.
  //   worldX = (mx - panX) / oldZoom
  //   panX'  = mx - worldX * newZoom
  panX.value = mx - ((mx - panX.value) / oldZoom) * newZoom;
  panY.value = my - ((my - panY.value) / oldZoom) * newZoom;

  emit('update:zoom', newZoom);
}

// ── Transform style ───────────────────────────────────────────────────────────
const transformStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${props.zoom})`,
  transformOrigin: '0 0',
}));

// ── Grid background ───────────────────────────────────────────────────────────
/**
 * The grid dots are painted via CSS background-image on the container.
 * We shift the background-position by (panX mod gridPx, panY mod gridPx) and
 * scale the background-size to match the current zoom so the dots appear to
 * belong to the canvas coordinate system.
 */
const gridStyle = computed(() => {
  const gridPx = GRID_SIZE * props.zoom;
  const ox = ((panX.value % gridPx) + gridPx) % gridPx;
  const oy = ((panY.value % gridPx) + gridPx) % gridPx;
  return {
    backgroundImage:
      'radial-gradient(circle, #2a2a3e 1px, transparent 1px)',
    backgroundSize:  `${gridPx}px ${gridPx}px`,
    backgroundPosition: `${ox}px ${oy}px`,
  };
});

// ── Cursor ────────────────────────────────────────────────────────────────────
const cursorStyle = computed(() => {
  if (isPanning.value)  return 'grabbing';
  if (spaceHeld.value)  return 'grab';
  if (isSelecting.value) return 'crosshair';
  return 'default';
});

// ── Rubber-band selection ─────────────────────────────────────────────────────
const isSelecting  = ref(false);
const selectionBox = ref({ x1: 0, y1: 0, x2: 0, y2: 0 });
let selectionStart = { x: 0, y: 0 };

function beginSelection(clientX, clientY) {
  const rect = containerRef.value.getBoundingClientRect();
  selectionStart = { x: clientX - rect.left, y: clientY - rect.top };
  selectionBox.value = {
    x1: selectionStart.x,
    y1: selectionStart.y,
    x2: selectionStart.x,
    y2: selectionStart.y,
  };
  isSelecting.value = true;
}

function updateSelection(clientX, clientY) {
  if (!isSelecting.value) return;
  const rect = containerRef.value.getBoundingClientRect();
  selectionBox.value.x2 = clientX - rect.left;
  selectionBox.value.y2 = clientY - rect.top;
}

function endSelection() {
  isSelecting.value = false;
}

// ── Draft wire — derived from editor store ───────────────────────────────────
const draftWire = computed(() => {
  const dw = editor.draftWire;
  if (!dw) return null;
  const fromPos = graph.getPortPosition(dw.fromNodeId, dw.fromPortId);
  if (!fromPos) return null;
  // Convert canvas coords to screen coords for the SVG overlay
  const fromScreen = {
    x: fromPos.x * props.zoom + panX.value,
    y: fromPos.y * props.zoom + panY.value,
  };
  return {
    fromX: fromScreen.x,
    fromY: fromScreen.y,
    toX: dw.mouseX,
    toY: dw.mouseY,
    portType: dw.portType,
  };
});

// ── Keyboard ──────────────────────────────────────────────────────────────────
function onKeyDown(e) {
  if (e.code === 'Space' && e.target === document.body) {
    e.preventDefault();
    spaceHeld.value = true;
  }
}
function onKeyUp(e) {
  if (e.code === 'Space') {
    spaceHeld.value = false;
    if (isPanning.value) endPan();
  }
}

// ── Unified pointer handlers ──────────────────────────────────────────────────
function onPointerDown(e) {
  // Middle mouse → always pan
  if (e.button === 1) {
    e.preventDefault();
    beginPan(e.clientX, e.clientY);
    return;
  }
  // Left mouse + space held → pan
  if (e.button === 0 && spaceHeld.value) {
    beginPan(e.clientX, e.clientY);
    return;
  }
  // Left mouse → rubber-band selection (only when clicking the canvas itself)
  if (e.button === 0 && e.target === containerRef.value) {
    beginSelection(e.clientX, e.clientY);
  }
}

function onPointerMove(e) {
  if (isPanning.value) {
    continuePan(e.clientX, e.clientY);
    return;
  }
  // Update draft wire endpoint (screen coords)
  if (editor.isDrawingWire) {
    const rect = containerRef.value.getBoundingClientRect();
    editor.updateDraftWire(e.clientX - rect.left, e.clientY - rect.top);
  }
  updateSelection(e.clientX, e.clientY);
}

function onPointerUp(e) {
  if (isPanning.value) {
    endPan();
    return;
  }
  if (editor.isDrawingWire) {
    editor.cancelDraftWire();
  }
  if (isSelecting.value) {
    endSelection();
  }
}

function onContextMenu(e) {
  e.preventDefault();
}

// ── Drop from palette ──────────────────────────────────────────────────────
function onDragOver(e) {
  if (e.dataTransfer.types.includes('application/x-node-type')) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }
}

function onDrop(e) {
  const typeName = e.dataTransfer.getData('application/x-node-type');
  if (!typeName) return;
  e.preventDefault();

  const rect = containerRef.value.getBoundingClientRect();
  const canvasX = snapToGrid((e.clientX - rect.left - panX.value) / props.zoom);
  const canvasY = snapToGrid((e.clientY - rect.top - panY.value) / props.zoom);

  const nodeData = registry.createNodeData(typeName, canvasX, canvasY);
  if (nodeData) {
    graph.addNode(nodeData);
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup',   onKeyUp);
  // Use the container element for the wheel listener (needs passive: false)
  containerRef.value?.addEventListener('wheel', onWheel, { passive: false });
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown);
  window.removeEventListener('keyup',   onKeyUp);
  containerRef.value?.removeEventListener('wheel', onWheel);
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
    @dragover="onDragOver"
    @drop="onDrop"
  >
    <!-- ── Pan/zoom transform wrapper ── -->
    <div class="canvas-transform" :style="transformStyle">
      <!-- Wire layer sits behind nodes -->
      <WireLayer />

      <!-- Nodes -->
      <NodeRenderer
        v-for="node in graph.nodeList"
        :key="node.id"
        :node="node"
      />
    </div>

    <!-- ── Selection box (screen coords, outside transform) ── -->
    <SelectionBox v-if="isSelecting" :box="selectionBox" />

    <!-- ── Draft wire overlay (screen coords) ── -->
    <DraftWire v-if="draftWire" :wire="draftWire" />
  </div>
</template>

<style scoped>
/* ── Canvas container ── */
.canvas-container {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background-color: #11111b;

  /* Prevent text selection during drag operations */
  user-select: none;
  -webkit-user-select: none;
}

/* ── Transform wrapper ── */
.canvas-transform {
  position: absolute;
  top: 0;
  left: 0;
  /* Large enough to never visually clip nodes near origin.
     Actual infinite canvas behaviour comes from pan; this just avoids
     clipped SVG wires at the boundary. */
  width: 4000px;
  height: 4000px;
  /* transform is set via :style binding */
}
</style>
