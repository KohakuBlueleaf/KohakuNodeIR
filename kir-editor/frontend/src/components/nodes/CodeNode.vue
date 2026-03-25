<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as monaco from 'monaco-editor'
import { registerKirLanguage } from '../../editor/kirLanguage.js'
import { useGraphStore } from '../../stores/graph.js'
import { isWasmReady } from '../../parser/wasmParser.js'
import { parse_kir } from '../../wasm/kohakunode_rs.js'

const props = defineProps({ node: { type: Object, required: true } })
const graph = useGraphStore()

const editorContainer = ref(null)
let editor = null
let resizeObserver = null
let ignoreChange = false
let validateTimer = null

onMounted(() => {
  registerKirLanguage(monaco)

  editor = monaco.editor.create(editorContainer.value, {
    value: props.node.properties?.code ?? '',
    language: 'kir',
    theme: 'kir-catppuccin',
    minimap: { enabled: false },
    lineNumbers: 'on',
    fontSize: 11,
    scrollBeyondLastLine: false,
    automaticLayout: false,
    overviewRulerLanes: 0,
    hideCursorInOverviewRuler: true,
    scrollbar: { vertical: 'auto', horizontal: 'auto' },
    wordWrap: 'off',
    tabSize: 4,
    insertSpaces: true,
    renderLineHighlight: 'line',
    contextmenu: false,
    fixedOverflowWidgets: true,
  })

  editor.onDidChangeModelContent(() => {
    if (ignoreChange) return
    const liveNode = graph.nodes.get(props.node.id)
    if (liveNode) {
      liveNode.properties.code = editor.getValue()
    }
    scheduleValidation()
  })

  // Prevent node drag when interacting with editor
  editorContainer.value.addEventListener('pointerdown', (e) => e.stopPropagation())
  editorContainer.value.addEventListener('mousedown', (e) => e.stopPropagation())

  resizeObserver = new ResizeObserver(() => {
    if (editor) editor.layout()
  })
  resizeObserver.observe(editorContainer.value)
})

// Sync external changes to properties.code back into the editor
watch(() => props.node.properties?.code, (newVal) => {
  if (editor && newVal !== editor.getValue()) {
    ignoreChange = true
    editor.setValue(newVal ?? '')
    ignoreChange = false
  }
})

function scheduleValidation() {
  if (validateTimer) clearTimeout(validateTimer)
  validateTimer = setTimeout(validateSyntax, 300)
}

async function validateSyntax() {
  if (!editor || !isWasmReady()) return
  const model = editor.getModel()
  if (!model) return
  const code = model.getValue()
  if (!code.trim()) {
    monaco.editor.setModelMarkers(model, 'kir', [])
    return
  }
  try {
    parse_kir(code)
    monaco.editor.setModelMarkers(model, 'kir', [])
  } catch (err) {
    monaco.editor.setModelMarkers(model, 'kir', [{
      severity: monaco.MarkerSeverity.Error,
      message: String(err.message || err),
      startLineNumber: 1,
      startColumn: 1,
      endLineNumber: model.getLineCount(),
      endColumn: model.getLineMaxColumn(model.getLineCount()),
    }])
  }
}

onBeforeUnmount(() => {
  if (validateTimer) clearTimeout(validateTimer)
  if (resizeObserver) resizeObserver.disconnect()
  if (editor) editor.dispose()
})
</script>

<template>
  <div class="code-node-body">
    <div ref="editorContainer" class="monaco-container" />
  </div>
</template>

<style scoped>
.code-node-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 160px;
  padding: 0;
}
.monaco-container {
  flex: 1;
  min-height: 160px;
  border-radius: 0 0 6px 6px;
  overflow: hidden;
}
</style>
