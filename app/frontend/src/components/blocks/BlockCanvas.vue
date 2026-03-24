<script setup>
// BlockCanvas.vue — scrollable/pannable surface that renders all block stacks.
// Also hosts the BlockPalette sidebar and handles palette drag-drop to create nodes.

import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { useGraphStore } from '../../stores/graph.js';
import { useNodeRegistryStore } from '../../stores/nodeRegistry.js';
import { GRID_SIZE }     from '../../utils/grid.js';
import { useBlockTree }  from './blockTree.js';
import BlockStack        from './BlockStack.vue';
import BlockPalette      from './BlockPalette.vue';
import { draggingNodeId, ghostPos } from '../../composables/useBlockDrag.js';

// ── Props / emits ──────────────────────────────────────────────────────────────
const props = defineProps({
  zoom: {
    type: Number,
    default: 1,
  },
});
const emit = defineEmits(['update:zoom']);

// ── Stores ─────────────────────────────────────────────────────────────────────
const graph = useGraphStore();
const registry = useNodeRegistryStore();
const { blockTree } = useBlockTree(graph);

// ── Refs ───────────────────────────────────────────────────────────────────────
const containerRef = ref(null);

// ── Pan state ─────────────────────────────────────────────────────────────────
const panX = ref(40);
const panY = ref(40);
const isPanning    = ref(false);
const spaceHeld    = ref(false);
let panStartX = 0;
let panStartY = 0;
let panOriginX = 0;
let panOriginY = 0;

function beginPan(clientX, clientY) {
  isPanning.value = true;
  panStartX  = clientX;
  panStartY  = clientY;
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
const ZOOM_MIN   = 0.1;
const ZOOM_MAX   = 4;
const ZOOM_SPEED = 0.001;

function onWheel(e) {
  e.preventDefault();
  const rect    = containerRef.value.getBoundingClientRect();
  const mx      = e.clientX - rect.left;
  const my      = e.clientY - rect.top;
  const oldZoom = props.zoom;
  const delta   = -e.deltaY * ZOOM_SPEED;
  const newZoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, +(oldZoom + delta * oldZoom).toFixed(4)));
  panX.value = mx - ((mx - panX.value) / oldZoom) * newZoom;
  panY.value = my - ((my - panY.value) / oldZoom) * newZoom;
  emit('update:zoom', newZoom);
}

// ── Transform style ───────────────────────────────────────────────────────────
const transformStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${props.zoom})`,
  transformOrigin: '0 0',
}));

// ── Dot grid background (matches EditorCanvas) ───────────────────────────────
const gridStyle = computed(() => {
  const gridPx = GRID_SIZE * props.zoom;
  const ox = ((panX.value % gridPx) + gridPx) % gridPx;
  const oy = ((panY.value % gridPx) + gridPx) % gridPx;
  return {
    backgroundImage:   'radial-gradient(circle, #2a2a3e 1px, transparent 1px)',
    backgroundSize:    `${gridPx}px ${gridPx}px`,
    backgroundPosition:`${ox}px ${oy}px`,
  };
});

// ── Cursor ────────────────────────────────────────────────────────────────────
const cursorStyle = computed(() => {
  if (isPanning.value) return 'grabbing';
  if (spaceHeld.value) return 'grab';
  return 'default';
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

// ── Pointer handlers ──────────────────────────────────────────────────────────
function onPointerDown(e) {
  if (e.button === 1) { e.preventDefault(); beginPan(e.clientX, e.clientY); return; }
  if (e.button === 0 && spaceHeld.value) { beginPan(e.clientX, e.clientY); return; }
  if (e.button === 0) {
    const isCanvas = e.target === containerRef.value || e.target.classList.contains('blocks-transform');
    if (isCanvas) beginPan(e.clientX, e.clientY);
  }
}
function onPointerMove(e) { if (isPanning.value) continuePan(e.clientX, e.clientY); }
function onPointerUp()    { if (isPanning.value) endPan(); }

// ── Stack layout: auto-position stacks in columns ─────────────────────────────
const STACK_COLUMN_GAP = 32;
const STACK_ROW_GAP    = 32;
const STACK_WIDTH      = 280;

function stackStyle(index) {
  const col = index;
  return {
    position: 'absolute',
    left: `${col * (STACK_WIDTH + STACK_COLUMN_GAP)}px`,
    top: `${STACK_ROW_GAP}px`,
    width: `${STACK_WIDTH}px`,
  };
}

// ── Palette drag-and-drop ──────────────────────────────────────────────────────
// Converts a screen-space drop position to canvas space, accounting for
// the canvas element's own offset, pan, and zoom.

const isDragOver = ref(false);

function screenToCanvas(clientX, clientY) {
  const rect = containerRef.value.getBoundingClientRect();
  const sx = clientX - rect.left;
  const sy = clientY - rect.top;
  return {
    x: (sx - panX.value) / props.zoom,
    y: (sy - panY.value) / props.zoom,
  };
}

function onDragOver(e) {
  // Only accept our custom block-type drag
  if (!e.dataTransfer.types.includes('application/x-block-type')) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
  isDragOver.value = true;
}

function onDragLeave() {
  isDragOver.value = false;
}

function onDrop(e) {
  isDragOver.value = false;
  const typeName = e.dataTransfer.getData('application/x-block-type');
  if (!typeName) return;
  e.preventDefault();

  const { x, y } = screenToCanvas(e.clientX, e.clientY);
  try {
    const nodeData = registry.createNodeData(typeName, x, y);
    graph.addNode(nodeData);
  } catch (err) {
    console.warn('[BlockCanvas] drop failed:', err.message);
  }
}

// ── Drag ghost label ──────────────────────────────────────────────────────────
function ghostNodeName() {
  if (!draggingNodeId.value) return '';
  const node = graph.nodes.get(draggingNodeId.value);
  return node?.name ?? '';
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup',   onKeyUp);
  containerRef.value?.addEventListener('wheel', onWheel, { passive: false });
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown);
  window.removeEventListener('keyup',   onKeyUp);
  containerRef.value?.removeEventListener('wheel', onWheel);
});
</script>

<template>
  <div class="blocks-root">
    <!-- ── Palette sidebar ── -->
    <BlockPalette />

    <!-- ── Canvas area ── -->
    <div
      ref="containerRef"
      class="blocks-canvas"
      :style="[gridStyle, { cursor: cursorStyle }]"
      :class="{ 'is-drag-over': isDragOver }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
      @contextmenu.prevent
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <!-- Pan/zoom transform wrapper -->
      <div class="blocks-transform" :style="transformStyle">

        <!-- Empty state -->
        <div v-if="!blockTree.stacks.length" class="blocks-empty">
          <span class="blocks-empty-label">Drag a block from the palette to get started.</span>
        </div>

        <!-- Block stacks -->
        <div
          v-for="(stack, i) in blockTree.stacks"
          :key="stack.rootNodeId"
          class="stack-wrapper"
          :style="stackStyle(i)"
        >
          <BlockStack :blocks="stack.blocks" />
        </div>

      </div>

      <!-- Drag-over highlight border -->
      <div v-if="isDragOver" class="drag-over-overlay" />
    </div>

    <!-- ── Block drag ghost ── -->
    <Teleport to="body">
      <div
        v-if="draggingNodeId && ghostPos"
        class="block-drag-ghost"
        :style="{ left: ghostPos.x + 'px', top: ghostPos.y + 'px' }"
      >
        {{ ghostNodeName() }}
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* ── Root: flex row containing palette + canvas ── */
.blocks-root {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

/* ── Canvas ── */
.blocks-canvas {
  position: relative;
  flex: 1;
  height: 100%;
  overflow: hidden;
  background-color: #11111b;
  user-select: none;
  -webkit-user-select: none;
}

/* ── Transform wrapper ── */
.blocks-transform {
  position: absolute;
  top: 0;
  left: 0;
  width: 6000px;
  height: 6000px;
}

/* ── Stack wrapper (absolute positioning within transform) ── */
.stack-wrapper {
  /* min-width set via inline style */
}

/* ── Empty state ── */
.blocks-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 13px;
  color: #45475a;
  text-align: center;
  pointer-events: none;
}

.blocks-empty-label {
  display: block;
}

/* ── Drag-over highlight ── */
.drag-over-overlay {
  position: absolute;
  inset: 0;
  border: 2px solid #89b4fa;
  border-radius: 4px;
  pointer-events: none;
  box-shadow: inset 0 0 20px rgba(137, 180, 250, 0.08);
}
</style>

<!-- Block drag ghost — teleported to body, so not scoped -->
<style>
.block-drag-ghost {
  position: fixed;
  z-index: 10000;
  pointer-events: none;
  transform: translate(-50%, -120%);
  background: #313244;
  border: 1.5px solid #89b4fa;
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #89b4fa;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
  user-select: none;
}
</style>
