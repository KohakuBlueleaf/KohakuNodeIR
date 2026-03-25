<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue';
import * as monaco from 'monaco-editor';
import { registerKirLanguage } from '../../editor/kirLanguage.js';
import { useGraphStore } from '../../stores/graph.js';
import { compileGraph } from '../../compiler/graphToIr.js';
import { graphToKirgraph } from '../../compiler/kirgraph.js';
import { compileGraphToKir, isWasmReady } from '../../parser/wasmParser.js';
import { detectAndParseAsync } from '../../parser/index.js';
import { parserResultToGraph } from '../../utils/parserResultToGraph.js';

const graph = useGraphStore();
const editorContainer = ref(null);
let editor = null;
const hideMeta = ref(false);

// When true, the editor content is the source of truth.
// Graph→editor sync is suppressed; editor→graph sync is active.
let editorIsSource = false;

// ── Compile graph → KIR text ──
async function graphToKir() {
  const nodes = graph.nodeList;
  const conns = graph.connectionList;
  if (!nodes.length) return '';

  const kirgraph = graphToKirgraph(nodes, conns);
  const pyKir = await compileGraphToKir(JSON.stringify(kirgraph));
  if (pyKir) return pyKir;

  const { ir } = compileGraph(nodes, conns);
  return ir;
}

// ── Sync graph → editor (only when graph changed from node UI, NOT from editor) ──
let graphSyncTimer = null;
watch(
  [() => graph.nodeList, () => graph.connectionList],
  () => {
    if (editorIsSource) return;
    clearTimeout(graphSyncTimer);
    graphSyncTimer = setTimeout(async () => {
      const kir = await graphToKir();
      if (editor && kir !== editor.getValue()) {
        // Temporarily mark as source to prevent the setValue triggering editor→graph
        editorIsSource = true;
        editor.setValue(kir);
        editorIsSource = false;
        if (hideMeta.value) updateMetaVisibility();
      }
    }, 300);
  },
  { deep: true },
);

// ── Parse editor content → graph (realtime, does NOT touch editor content) ──
let parseSyncTimer = null;
function onEditorChange() {
  // Mark editor as source of truth — suppress graph→editor sync
  editorIsSource = true;
  clearTimeout(parseSyncTimer);
  parseSyncTimer = setTimeout(async () => {
    const text = editor?.getValue();
    if (!text?.trim()) {
      editorIsSource = false;
      return;
    }

    try {
      const result = await detectAndParseAsync(text);
      if (!result?.nodes?.length) {
        editorIsSource = false;
        return;
      }

      const { nodes, connections } = parserResultToGraph(result.nodes, result.edges);
      graph.clear();
      for (const node of nodes) graph.addNode(node);
      for (const conn of connections) {
        graph.addConnection(conn.fromNodeId, conn.fromPortId, conn.toNodeId, conn.toPortId, conn.portType);
      }
      monaco.editor.setModelMarkers(editor.getModel(), 'kir', []);
    } catch (err) {
      if (editor) {
        monaco.editor.setModelMarkers(editor.getModel(), 'kir', [{
          severity: monaco.MarkerSeverity.Error,
          message: err.message || 'Parse error',
          startLineNumber: 1, startColumn: 1,
          endLineNumber: 1, endColumn: 1,
        }]);
      }
    }
    // Keep editorIsSource=true — it stays true until user switches away
    // from code view or until a graph→editor sync from node UI
  }, 600);
}

// Called when user switches to this view — refresh from graph if editor wasn't source
function refreshFromGraph() {
  if (!editorIsSource) {
    graphToKir().then((kir) => {
      if (editor && kir !== editor.getValue()) {
        editorIsSource = true;
        editor.setValue(kir);
        editorIsSource = false;
        if (hideMeta.value) updateMetaVisibility();
      }
    });
  }
}

// Reset source flag when editor loses focus (user switched to node/block view)
function onEditorBlur() {
  // Small delay — don't immediately reset during tab switches within code view
  setTimeout(() => {
    if (!editorContainer.value?.contains(document.activeElement)) {
      editorIsSource = false;
    }
  }, 200);
}

defineExpose({ refreshFromGraph });

// ── @meta visibility toggle ──
function updateMetaVisibility() {
  if (!editor) return;
  const model = editor.getModel();
  if (!model) return;

  if (!hideMeta.value) {
    editor.setHiddenAreas([]);
    return;
  }

  // Find all @meta lines and hide them
  const ranges = [];
  const lineCount = model.getLineCount();
  for (let i = 1; i <= lineCount; i++) {
    const line = model.getLineContent(i);
    if (/^\s*@meta\b/.test(line)) {
      ranges.push(new monaco.Range(i, 1, i, 1));
    }
  }
  editor.setHiddenAreas(ranges);
}

function toggleMeta() {
  hideMeta.value = !hideMeta.value;
  updateMetaVisibility();
}

// ── Lifecycle ──
onMounted(async () => {
  await nextTick();
  registerKirLanguage(monaco);

  const initialKir = await graphToKir();

  editor = monaco.editor.create(editorContainer.value, {
    value: initialKir,
    language: 'kir',
    theme: 'kir-catppuccin',
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    scrollBeyondLastLine: false,
    wordWrap: 'off',
    tabSize: 4,
    insertSpaces: true,
    automaticLayout: true,
    padding: { top: 8 },
  });

  editor.onDidChangeModelContent(() => {
    onEditorChange();
    if (hideMeta.value) updateMetaVisibility();
  });

  editor.onDidBlurEditorWidget(onEditorBlur);
});

onBeforeUnmount(() => {
  clearTimeout(graphSyncTimer);
  clearTimeout(parseSyncTimer);
  editor?.dispose();
  editor = null;
});
</script>

<template>
  <div class="kir-code-editor-root">
    <div class="kir-code-editor-header">
      <span class="kir-code-editor-title">KIR Code Editor</span>
      <span class="kir-code-editor-badge" :class="isWasmReady() ? 'badge--ready' : 'badge--loading'">
        {{ isWasmReady() ? 'WASM' : '...' }}
      </span>
      <button
        class="meta-toggle-btn"
        :class="{ 'meta-toggle-btn--active': hideMeta }"
        :title="hideMeta ? 'Show @meta annotations' : 'Hide @meta annotations'"
        @click="toggleMeta"
      >
        @meta {{ hideMeta ? 'hidden' : 'visible' }}
      </button>
      <span class="kir-code-editor-hint">
        Edit KIR directly — changes sync with the node graph
      </span>
    </div>
    <div ref="editorContainer" class="kir-code-editor-body" />
  </div>
</template>

<style scoped>
.kir-code-editor-root {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: #1e1e2e;
  overflow: hidden;
}

.kir-code-editor-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}

.kir-code-editor-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
}

.kir-code-editor-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid;
}

.badge--ready {
  color: #a6e3a1;
  border-color: rgba(166, 227, 161, 0.4);
  background: rgba(166, 227, 161, 0.08);
}

.badge--loading {
  color: #6c7086;
  border-color: rgba(108, 112, 134, 0.4);
}

.kir-code-editor-hint {
  font-size: 10px;
  color: #45475a;
  margin-left: auto;
}

.meta-toggle-btn {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  border: 1px solid #45475a;
  background: transparent;
  color: #a6adc8;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s, color 0.1s;
}

.meta-toggle-btn:hover {
  background: #313244;
  color: #cdd6f4;
}

.meta-toggle-btn--active {
  color: #f5c2e7;
  border-color: rgba(245, 194, 231, 0.4);
  background: rgba(245, 194, 231, 0.08);
}

.kir-code-editor-body {
  flex: 1;
  min-height: 0;
}
</style>

