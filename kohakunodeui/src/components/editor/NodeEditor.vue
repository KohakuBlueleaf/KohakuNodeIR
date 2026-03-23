<script setup>
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useEditorStore } from '../../stores/editor.js';
import { useGraphStore } from '../../stores/graph.js';
import EditorCanvas from './EditorCanvas.vue';
import NodePalette from '../panels/NodePalette.vue';
import PropertyPanel from '../panels/PropertyPanel.vue';
import NodeDefEditor from '../panels/NodeDefEditor.vue';
import IrPreview from '../panels/IrPreview.vue';
import { graphToKirgraph, kirgraphToGraph } from '../../compiler/kirgraph.js';

const editorStore = useEditorStore();
const graph = useGraphStore();

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

// --- Save graph as .kirgraph ---
function saveGraph() {
  const kirgraph = graphToKirgraph(graph.nodeList, graph.connectionList);
  const json = JSON.stringify(kirgraph, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'graph.kirgraph';
  a.click();
  URL.revokeObjectURL(url);
  ElMessage({ message: 'Graph saved as graph.kirgraph', type: 'success', duration: 1800 });
}

// --- Load graph from .kirgraph ---
function loadGraph() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.kirgraph,.json';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const kirgraph = JSON.parse(ev.target.result);
        const { nodes, connections } = kirgraphToGraph(kirgraph);
        graph.clear();
        for (const node of nodes) graph.addNode(node);
        for (const conn of connections) {
          graph.addConnection(
            conn.fromNodeId,
            conn.fromPortId,
            conn.toNodeId,
            conn.toPortId,
            conn.portType,
          );
        }
        ElMessage({ message: `Loaded ${nodes.length} node(s) from ${file.name}`, type: 'success', duration: 2000 });
      } catch (err) {
        ElMessage({ message: `Failed to load graph: ${err.message}`, type: 'error', duration: 3000 });
      }
    };
    reader.readAsText(file);
  };
  input.click();
}
</script>

<template>
  <div class="editor-root">

    <!-- ── Toolbar ── -->
    <header class="toolbar">
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

      <!-- Title -->
      <span class="editor-title">KohakuNode IR</span>

      <div class="toolbar-sep" />

      <!-- Save / Load -->
      <div class="toolbar-group">
        <button class="tool-btn tool-btn--save" title="Save graph as .kirgraph" @click="saveGraph">
          <span class="i-carbon-save" />
          Save
        </button>
        <button class="tool-btn tool-btn--load" title="Load graph from .kirgraph" @click="loadGraph">
          <span class="i-carbon-folder-open" />
          Load
        </button>
      </div>
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

.tool-btn--save {
  color: #a6e3a1;
}
.tool-btn--save:hover {
  color: #a6e3a1;
  border-color: rgba(166, 227, 161, 0.5);
}

.tool-btn--load {
  color: #89b4fa;
}
.tool-btn--load:hover {
  color: #89b4fa;
  border-color: rgba(137, 180, 250, 0.5);
}

.editor-title {
  font-size: 12px;
  font-weight: 600;
  color: #6c7086;
  letter-spacing: 0.05em;
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
