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
let ignoreModelChange = false;
let ignoreGraphChange = false;

// ── Compile graph → KIR text ──
async function graphToKir() {
  const nodes = graph.nodeList;
  const conns = graph.connectionList;
  if (!nodes.length) return '';

  const kirgraph = graphToKirgraph(nodes, conns);
  const pyKir = await compileGraphToKir(JSON.stringify(kirgraph));
  if (pyKir) return pyKir;

  // Fallback to JS compiler
  const { ir } = compileGraph(nodes, conns);
  return ir;
}

// ── Sync graph → editor (when graph changes externally) ──
let graphSyncTimer = null;
watch(
  [() => graph.nodeList, () => graph.connectionList],
  () => {
    if (ignoreGraphChange) return;
    clearTimeout(graphSyncTimer);
    graphSyncTimer = setTimeout(async () => {
      const kir = await graphToKir();
      if (editor && kir !== editor.getValue()) {
        ignoreModelChange = true;
        editor.setValue(kir);
        ignoreModelChange = false;
      }
    }, 300);
  },
  { deep: true },
);

// ── Parse KIR text → graph (when user edits code) ──
let parseSyncTimer = null;
function onEditorChange() {
  if (ignoreModelChange) return;
  clearTimeout(parseSyncTimer);
  parseSyncTimer = setTimeout(async () => {
    const text = editor?.getValue();
    if (!text?.trim()) return;

    try {
      const result = await detectAndParseAsync(text);
      if (!result?.nodes?.length) return;

      const { nodes, connections } = parserResultToGraph(result.nodes, result.edges);
      ignoreGraphChange = true;
      graph.clear();
      for (const node of nodes) graph.addNode(node);
      for (const conn of connections) {
        graph.addConnection(conn.fromNodeId, conn.fromPortId, conn.toNodeId, conn.toPortId, conn.portType);
      }
      // Clear error markers
      monaco.editor.setModelMarkers(editor.getModel(), 'kir', []);
    } catch (err) {
      // Show parse error in editor
      if (editor) {
        monaco.editor.setModelMarkers(editor.getModel(), 'kir', [{
          severity: monaco.MarkerSeverity.Error,
          message: err.message || 'Parse error',
          startLineNumber: 1, startColumn: 1,
          endLineNumber: 1, endColumn: 1,
        }]);
      }
    } finally {
      ignoreGraphChange = false;
    }
  }, 600);
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

  editor.onDidChangeModelContent(onEditorChange);
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

.kir-code-editor-body {
  flex: 1;
  min-height: 0;
}
</style>
