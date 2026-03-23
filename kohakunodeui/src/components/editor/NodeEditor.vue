<script setup>
import { ref } from 'vue';
import { useEditorStore } from '../../stores/editor.js';
import EditorCanvas from './EditorCanvas.vue';
import NodePalette from '../panels/NodePalette.vue';
import PropertyPanel from '../panels/PropertyPanel.vue';
import NodeDefEditor from '../panels/NodeDefEditor.vue';
import IrPreview from '../panels/IrPreview.vue';

const editorStore = useEditorStore();

// --- Mode (synced with store) ---
const mode = ref(editorStore.mode);

// --- Zoom state (lifted here so toolbar controls can drive it) ---
const zoomLevel = ref(1);
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.25;

function zoomIn() {
  zoomLevel.value = Math.min(ZOOM_MAX, +(zoomLevel.value + ZOOM_STEP).toFixed(2));
}
function zoomOut() {
  zoomLevel.value = Math.max(ZOOM_MIN, +(zoomLevel.value - ZOOM_STEP).toFixed(2));
}
function resetZoom() {
  zoomLevel.value = 1;
}

// --- Undo / Redo stubs (wired to history store later) ---
function undo() { /* TODO: useHistoryStore().undo() */ }
function redo() { /* TODO: useHistoryStore().redo() */ }

// --- IR Preview collapse ---
const irOpen = ref(false);

// --- NodeDefEditor dialog ---
const nodeDefEditorOpen = ref(false);
const nodeDefEditorTarget = ref(null); // null = create new, object = edit existing

function openNodeDefEditor(def) {
  nodeDefEditorTarget.value = def ?? null;
  nodeDefEditorOpen.value = true;
}
</script>

<template>
  <div class="editor-root">

    <!-- ── Toolbar ── -->
    <header class="toolbar">
      <!-- Mode toggle -->
      <div class="toolbar-group">
        <button
          class="mode-btn"
          :class="{ active: mode === 'dataflow' }"
          @click="mode = 'dataflow'; editorStore.setMode('dataflow')"
        >
          Dataflow
        </button>
        <button
          class="mode-btn"
          :class="{ active: mode === 'controlflow' }"
          @click="mode = 'controlflow'; editorStore.setMode('controlflow')"
        >
          Control Flow
        </button>
      </div>

      <div class="toolbar-sep" />

      <!-- Zoom controls -->
      <div class="toolbar-group">
        <button class="tool-btn" title="Zoom out" @click="zoomOut">−</button>
        <span class="zoom-label" @click="resetZoom" title="Reset zoom">
          {{ Math.round(zoomLevel * 100) }}%
        </span>
        <button class="tool-btn" title="Zoom in" @click="zoomIn">+</button>
      </div>

      <div class="toolbar-sep" />

      <!-- Undo / Redo -->
      <div class="toolbar-group">
        <button class="tool-btn" title="Undo (Ctrl+Z)" @click="undo">
          <span class="i-carbon-undo" />
          Undo
        </button>
        <button class="tool-btn" title="Redo (Ctrl+Y)" @click="redo">
          <span class="i-carbon-redo" />
          Redo
        </button>
      </div>

      <!-- Spacer -->
      <div style="flex: 1" />

      <!-- Mode indicator badge -->
      <span class="mode-badge" :class="mode">
        {{ mode === 'dataflow' ? 'Data Flow' : 'Control Flow' }}
      </span>
    </header>

    <!-- ── Main body ── -->
    <div class="editor-body">

      <!-- Left: Node Palette -->
      <aside class="panel panel-left">
        <div class="panel-title">Node Palette</div>
        <NodePalette @open-node-def-editor="openNodeDefEditor" />
      </aside>

      <!-- Centre: Canvas -->
      <main class="canvas-area">
        <EditorCanvas :zoom="zoomLevel" @update:zoom="zoomLevel = $event" />
      </main>

      <!-- Right: Property Panel -->
      <aside class="panel panel-right">
        <div class="panel-title">Properties</div>
        <PropertyPanel />
      </aside>

    </div>

    <!-- ── Node Def Editor dialog ── -->
    <NodeDefEditor
      v-model="nodeDefEditorOpen"
      :definition="nodeDefEditorTarget"
    />

    <!-- ── IR Preview (collapsible bottom strip) ── -->
    <div class="ir-preview-wrapper" :class="{ open: irOpen }">
      <div class="ir-preview-header" @click="irOpen = !irOpen">
        <span>IR Preview</span>
        <span class="ir-toggle-icon">{{ irOpen ? '▼' : '▲' }}</span>
      </div>
      <div v-show="irOpen" class="ir-preview-body">
        <IrPreview />
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ── Root layout ── */
.editor-root {
  display: grid;
  grid-template-rows: 44px 1fr auto;
  width: 100%;
  height: 100%;
  background: #11111b;
  color: #cdd6f4;
  overflow: hidden;
}

/* ── Toolbar ── */
.toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 12px;
  background: #181825;
  border-bottom: 1px solid #313244;
  user-select: none;
  overflow: hidden;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 2px;
}

.toolbar-sep {
  width: 1px;
  height: 22px;
  background: #313244;
  margin: 0 6px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: #cdd6f4;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  white-space: nowrap;
}
.tool-btn:hover {
  background: #313244;
  border-color: #45475a;
}
.tool-btn:active {
  background: #45475a;
}

.mode-btn {
  padding: 4px 12px;
  background: transparent;
  border: 1px solid #45475a;
  border-radius: 4px;
  color: #a6adc8;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.mode-btn:hover {
  background: #313244;
  color: #cdd6f4;
}
.mode-btn.active {
  background: #313244;
  color: #89b4fa;
  border-color: #89b4fa;
}

.zoom-label {
  min-width: 44px;
  text-align: center;
  font-size: 12px;
  color: #a6adc8;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background 0.12s;
}
.zoom-label:hover {
  background: #313244;
  color: #cdd6f4;
}

.mode-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
  letter-spacing: 0.03em;
}
.mode-badge.dataflow {
  background: rgba(137, 180, 250, 0.15);
  color: #89b4fa;
  border: 1px solid rgba(137, 180, 250, 0.3);
}
.mode-badge.controlflow {
  background: rgba(250, 179, 135, 0.15);
  color: #fab387;
  border: 1px solid rgba(250, 179, 135, 0.3);
}

/* ── Main body (3-column) ── */
.editor-body {
  display: grid;
  grid-template-columns: 240px 1fr 280px;
  overflow: hidden;
}

/* ── Side panels ── */
.panel {
  display: flex;
  flex-direction: column;
  background: #181825;
  overflow: hidden;
}
.panel-left {
  border-right: 1px solid #313244;
}
.panel-right {
  border-left: 1px solid #313244;
}

.panel-title {
  padding: 10px 14px 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
  border-bottom: 1px solid #313244;
}

.panel-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.placeholder-text {
  font-size: 12px;
  color: #45475a;
  text-align: center;
}

/* ── Canvas area ── */
.canvas-area {
  overflow: hidden;
  position: relative;
}

/* ── IR Preview strip ── */
.ir-preview-wrapper {
  background: #181825;
  border-top: 1px solid #313244;
  /* collapsed: just the header bar */
}

.ir-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 14px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
  cursor: pointer;
  user-select: none;
  transition: background 0.12s;
}
.ir-preview-header:hover {
  background: #1e1e2e;
}

.ir-toggle-icon {
  font-size: 10px;
}

.ir-preview-body {
  height: 220px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-top: 1px solid #313244;
}
</style>
