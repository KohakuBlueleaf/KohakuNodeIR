<script setup>
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useEditorStore } from '../../stores/editor.js';
import { useGraphStore } from '../../stores/graph.js';
import { useHistoryStore } from '../../stores/history.js';
import { graphToKirgraph, kirgraphToGraph } from '../../compiler/kirgraph.js';
import { compileGraph } from '../../compiler/graphToIr.js';
import { autoLayout, graphStoreToLayoutFormat, applyLayoutToStore } from '../../layout/autoLayout.js';
import { executeKirStreaming } from '../../api/backend.js';
import { detectAndParseAsync } from '../../parser/index.js';
import { parserResultToGraph } from '../../utils/parserResultToGraph.js';

// ── Props ──────────────────────────────────────────────────────────────────────
const props = defineProps({
  zoom: {
    type: Number,
    default: 1,
  },
  // Which view is currently active — affects what zoom controls mean
  viewMode: {
    type: String,
    default: 'graph',
  },
});

const emit = defineEmits(['update:zoom', 'open-ir-preview']);

// ── Stores ─────────────────────────────────────────────────────────────────────
const editorStore = useEditorStore();
const graph = useGraphStore();
const historyStore = useHistoryStore();

// ── Zoom ───────────────────────────────────────────────────────────────────────
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.25;

function zoomIn() {
  const next = Math.min(ZOOM_MAX, +(props.zoom + ZOOM_STEP).toFixed(2));
  emit('update:zoom', next);
}

function zoomOut() {
  const next = Math.max(ZOOM_MIN, +(props.zoom - ZOOM_STEP).toFixed(2));
  emit('update:zoom', next);
}

function resetZoom() {
  emit('update:zoom', 1);
}

// ── Undo / Redo ────────────────────────────────────────────────────────────────
function undo() {
  historyStore.undo();
}

function redo() {
  historyStore.redo();
}

// ── Run ────────────────────────────────────────────────────────────────────────
const isRunning = ref(false);
let _cancelRun = null;

function runGraph() {
  if (isRunning.value) {
    _cancelRun?.();
    _cancelRun = null;
    isRunning.value = false;
    ElMessage({ message: 'Execution cancelled.', type: 'info', duration: 1500 });
    return;
  }

  if (!graph.nodeList.length) {
    ElMessage({ message: 'Graph is empty — add some nodes first.', type: 'warning', duration: 2000 });
    return;
  }

  // Compile graph to KIR text and execute that directly
  // (avoids mismatch between preview variable names and execution variable names)
  const { ir } = compileGraph(graph.nodeList, graph.connectionList);
  isRunning.value = true;

  // Ask the parent to open IR preview so results are visible
  emit('open-ir-preview');

  const outputLines = [];
  const variables = {};

  const { cancel, ws } = executeKirStreaming(ir, {
    onOutput(text) {
      outputLines.push(text.replace(/\n$/, ''));
    },
    onError(msg) {
      isRunning.value = false;
      _cancelRun = null;
      ElMessage({ message: `Execution error: ${msg}`, type: 'error', duration: 5000 });
    },
    onVariable(name, value) {
      variables[name] = value;
    },
    onCompleted(vars) {
      isRunning.value = false;
      _cancelRun = null;
      const varCount = Object.keys(vars).length;
      const summary = outputLines.length
        ? outputLines.slice(-3).join(' | ')
        : varCount
          ? `${varCount} variable${varCount !== 1 ? 's' : ''} set`
          : 'done';
      ElMessage({
        message: `Run complete — ${summary}`,
        type: 'success',
        duration: 3000,
      });
    },
  });

  _cancelRun = cancel;

  ws.onerror = () => {
    isRunning.value = false;
    _cancelRun = null;
    ElMessage({
      message: 'Backend connection failed — is the server running on port 48888?',
      type: 'error',
      duration: 5000,
    });
  };

  ws.onclose = (event) => {
    isRunning.value = false;
    _cancelRun = null;
    if (event.code !== 1000) {
      ElMessage({ message: `Connection closed (code ${event.code})`, type: 'warning', duration: 3000 });
    }
  };
}

// ── Save ───────────────────────────────────────────────────────────────────────
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

// ── Load ───────────────────────────────────────────────────────────────────────
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

// ── Import ─────────────────────────────────────────────────────────────────────

// parserResultToGraph imported from ../../utils/parserResultToGraph.js

const isImporting = ref(false);

function importGraph() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.kir,.kirgraph,.json';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    isImporting.value = true;
    ElMessage({ message: `Importing ${file.name}…`, type: 'info', duration: 1500 });
    try {
      const content = await file.text();
      const result = await detectAndParseAsync(content, file.name);
      if (!result || !result.nodes || result.nodes.length === 0) {
        ElMessage({ message: 'Import produced an empty graph — check the file format.', type: 'warning', duration: 3000 });
        return;
      }
      const { nodes, connections } = parserResultToGraph(result.nodes, result.edges);
      graph.clear();
      for (const node of nodes) graph.addNode(node);
      for (const conn of connections) {
        graph.addConnection(conn.fromNodeId, conn.fromPortId, conn.toNodeId, conn.toPortId, conn.portType);
      }
      ElMessage({
        message: `Imported ${nodes.length} node(s) from ${file.name} (${result.format})`,
        type: 'success',
        duration: 2500,
      });
    } catch (err) {
      ElMessage({ message: `Import failed: ${err.message}`, type: 'error', duration: 4000 });
    } finally {
      isImporting.value = false;
    }
  };
  input.click();
}

// ── Auto Layout ────────────────────────────────────────────────────────────────
function runAutoLayout() {
  if (!graph.nodeList.length) {
    ElMessage({ message: 'Graph is empty — nothing to lay out.', type: 'warning', duration: 2000 });
    return;
  }
  const { nodes: layoutNodes, edges: layoutEdges } = graphStoreToLayoutFormat(
    graph.nodeList,
    graph.connectionList,
  );
  autoLayout(layoutNodes, layoutEdges);
  graph.beginMove();
  applyLayoutToStore(layoutNodes, graph);
  ElMessage({ message: 'Auto layout applied.', type: 'success', duration: 1500 });
}

// ── Export .kir ────────────────────────────────────────────────────────────────
function saveAsKir() {
  if (!graph.nodeList.length) {
    ElMessage({ message: 'Graph is empty — nothing to export.', type: 'warning', duration: 2000 });
    return;
  }
  const { ir, errors } = compileGraph(graph.nodeList, graph.connectionList);
  if (errors.length) {
    ElMessage({ message: `Compile warning: ${errors[0]}`, type: 'warning', duration: 3000 });
  }
  const blob = new Blob([ir], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'graph.kir';
  a.click();
  URL.revokeObjectURL(url);
  ElMessage({ message: 'Graph exported as graph.kir', type: 'success', duration: 1800 });
}

// ── Copy KIR ───────────────────────────────────────────────────────────────────
async function copyKirToClipboard() {
  if (!graph.nodeList.length) {
    ElMessage({ message: 'Graph is empty — nothing to copy.', type: 'warning', duration: 2000 });
    return;
  }
  const { ir, errors } = compileGraph(graph.nodeList, graph.connectionList);
  if (errors.length) {
    ElMessage({ message: `Compile warning: ${errors[0]}`, type: 'warning', duration: 3000 });
  }
  try {
    await navigator.clipboard.writeText(ir);
    ElMessage({ message: 'KIR text copied to clipboard.', type: 'success', duration: 1800 });
  } catch {
    ElMessage({ message: 'Clipboard write failed — check browser permissions.', type: 'error', duration: 3000 });
  }
}
</script>

<template>
  <header class="toolbar">
    <!-- Zoom controls -->
    <div class="toolbar-group">
      <button class="tool-btn" title="Zoom out" @click="zoomOut">−</button>
      <span class="zoom-label" title="Reset zoom" @click="resetZoom">
        {{ Math.round(zoom * 100) }}%
      </span>
      <button class="tool-btn" title="Zoom in" @click="zoomIn">+</button>
    </div>

    <div class="toolbar-sep" />

    <!-- Control ports toggle (node graph only) -->
    <div v-if="viewMode === 'graph'" class="toolbar-group">
      <button
        class="tool-btn"
        :class="{ 'tool-btn--active': editorStore.showCtrlPorts }"
        title="Toggle control flow ports"
        @click="editorStore.showCtrlPorts = !editorStore.showCtrlPorts"
      >
        <span class="i-carbon-flow" />
        Ctrl Ports
      </button>
    </div>

    <div v-if="viewMode === 'graph'" class="toolbar-sep" />

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

    <div class="toolbar-sep" />

    <!-- Run -->
    <div class="toolbar-group">
      <button
        class="tool-btn tool-btn--run"
        :class="{ 'tool-btn--run-active': isRunning }"
        :title="isRunning ? 'Click to cancel execution' : 'Run graph on backend (opens IR panel)'"
        @click="runGraph"
      >
        <span :class="isRunning ? 'i-carbon-stop-filled' : 'i-carbon-play-filled'" />
        {{ isRunning ? 'Stop' : 'Run' }}
      </button>
    </div>

    <!-- Auto Layout -->
    <div class="toolbar-group">
      <button class="tool-btn tool-btn--layout" title="Auto-layout all nodes" @click="runAutoLayout">
        <span class="i-carbon-chart-network" />
        Auto Layout
      </button>
    </div>

    <!-- Spacer -->
    <div style="flex: 1" />

    <!-- Title -->
    <span class="editor-title">KohakuNode IR</span>

    <div class="toolbar-sep" />

    <!-- Save / Load / Export -->
    <div class="toolbar-group">
      <button class="tool-btn tool-btn--save" title="Save graph as .kirgraph" @click="saveGraph">
        <span class="i-carbon-save" />
        Save
      </button>
      <button class="tool-btn tool-btn--load" title="Load graph from .kirgraph" @click="loadGraph">
        <span class="i-carbon-folder-open" />
        Load
      </button>
      <button
        class="tool-btn tool-btn--import"
        :disabled="isImporting"
        title="Import .kir, .kirgraph, or ComfyUI .json — auto-detects format"
        @click="importGraph"
      >
        <span class="i-carbon-upload" />
        {{ isImporting ? 'Importing…' : 'Import' }}
      </button>
      <button class="tool-btn tool-btn--export" title="Export compiled KIR as .kir file" @click="saveAsKir">
        <span class="i-carbon-document-export" />
        .kir
      </button>
      <button class="tool-btn tool-btn--copy" title="Copy compiled KIR text to clipboard" @click="copyKirToClipboard">
        <span class="i-carbon-copy" />
        Copy KIR
      </button>
    </div>
  </header>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 12px;
  height: 44px;
  background: #181825;
  border-bottom: 1px solid #313244;
  user-select: none;
  overflow: hidden;
  flex-shrink: 0;
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

.tool-btn--active {
  color: #fab387;
  border-color: rgba(250, 179, 135, 0.4);
  background: rgba(250, 179, 135, 0.08);
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

.tool-btn--import {
  color: #74c7ec;
}
.tool-btn--import:hover {
  color: #74c7ec;
  border-color: rgba(116, 199, 236, 0.5);
}
.tool-btn--import:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tool-btn--layout {
  color: #cba6f7;
}
.tool-btn--layout:hover {
  color: #cba6f7;
  border-color: rgba(203, 166, 247, 0.5);
}

.tool-btn--export {
  color: #f9e2af;
}
.tool-btn--export:hover {
  color: #f9e2af;
  border-color: rgba(249, 226, 175, 0.5);
}

.tool-btn--copy {
  color: #94e2d5;
}
.tool-btn--copy:hover {
  color: #94e2d5;
  border-color: rgba(148, 226, 213, 0.5);
}

.tool-btn--run {
  color: #a6e3a1;
  font-weight: 600;
}
.tool-btn--run:hover {
  color: #a6e3a1;
  border-color: rgba(166, 227, 161, 0.5);
  background: rgba(166, 227, 161, 0.08);
}
.tool-btn--run-active {
  color: #f9e2af;
  border-color: rgba(249, 226, 175, 0.5) !important;
  background: rgba(249, 226, 175, 0.08) !important;
  animation: run-pulse 1.2s ease-in-out infinite;
}
@keyframes run-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.65; }
}

.editor-title {
  font-size: 12px;
  font-weight: 600;
  color: #6c7086;
  letter-spacing: 0.05em;
}
</style>
