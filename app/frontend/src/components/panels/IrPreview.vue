<script setup>
import { ref, computed, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useGraphStore } from '../../stores/graph.js';
import { compileGraph } from '../../compiler/graphToIr.js';
import { graphToKirgraph } from '../../compiler/kirgraph.js';
import { executeKirgraphStreaming } from '../../api/backend.js';
import { compileGraphToKir, isPyodideReady } from '../../parser/pyodideParser.js';

const graph = useGraphStore();

// ---- Panel tab: 'kir' | 'kirgraph' ----
const activeTab = ref('kir');

// ---- Compilation mode ----
const mode = ref('controlflow');

// ---- Reactive IR text ----
const irText = ref('');
const compileErrors = ref([]);

// 'python' | 'js' | 'loading'
const compilerSource = ref('loading');

// Recompute whenever the graph changes or mode changes.
// Tries the Pyodide Python compiler first; falls back to the JS compiler.
watch(
  [() => graph.nodeList, () => graph.connectionList, mode],
  async ([nodes, conns]) => {
    if (!nodes.length) {
      irText.value = '';
      compileErrors.value = [];
      compilerSource.value = 'python';
      return;
    }

    const kirgraph = graphToKirgraph(nodes, conns);
    const pyKir = await compileGraphToKir(JSON.stringify(kirgraph));

    if (pyKir !== null) {
      irText.value = pyKir;
      compileErrors.value = [];
      compilerSource.value = 'python';
    } else {
      // Pyodide not ready — fall back to JS compiler
      const { ir, errors } = compileGraph(nodes, conns);
      irText.value = ir;
      compileErrors.value = errors;
      compilerSource.value = isPyodideReady() ? 'js' : 'loading';
    }
  },
  { immediate: true, deep: true },
);

// ---- Reactive kirgraph JSON ----
const kirgraphJson = computed(() => {
  const kg = graphToKirgraph(graph.nodeList, graph.connectionList);
  return JSON.stringify(kg, null, 2);
});

// ---- Line count for gutter ----
const displayText = computed(() => activeTab.value === 'kirgraph' ? kirgraphJson.value : irText.value);
const lineCount   = computed(() => displayText.value.split('\n').length);

// ---- Syntax highlight ----
// Regex-based highlighter for KIR syntax
function highlight(text) {
  // Process line-by-line to avoid regex corruption between injected spans
  return text.split('\n').map(highlightLine).join('\n');
}

function highlightLine(line) {
  // Escape HTML
  let s = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Comment lines — wrap entire line and return early
  if (/^\s*#/.test(s)) {
    return `<span class="ir-comment">${s}</span>`;
  }

  // Extract and protect string literals + backtick labels before other highlighting.
  // Replace them with placeholders, highlight the rest, then restore.
  const tokens = [];
  function stash(match, cls) {
    const id = `\x00${tokens.length}\x00`;
    tokens.push(`<span class="${cls}">${match}</span>`);
    return id;
  }

  // Strings first (double-quoted)
  s = s.replace(/"([^"\\]*(\\.[^"\\]*)*)"/g, (m) => stash(m, 'ir-string'));
  // Backtick labels
  s = s.replace(/`[^`]*`/g, (m) => stash(m, 'ir-label'));

  // Now safe to highlight without hitting quotes inside span attributes
  s = s.replace(/(@(?:meta|mode|def|dataflow)\b)/g, '<span class="ir-directive">$1</span>');
  s = s.replace(/\b(branch|switch|jump|parallel)\b/g, '<span class="ir-keyword">$1</span>');
  s = s.replace(/\b(True|False|None)\b/g, '<span class="ir-literal">$1</span>');
  s = s.replace(/^(\s*\w+)(:)$/g, '<span class="ir-label">$1$2</span>');
  s = s.replace(/\b(\d+(\.\d+)?)\b/g, '<span class="ir-number">$1</span>');
  s = s.replace(/^(\s*)(\w+)(\s*=)/g, '$1<span class="ir-var">$2</span>$3');
  s = s.replace(/\)([\w.]+)\(/g, ')<span class="ir-func">$1</span>(');

  // Restore stashed tokens
  s = s.replace(/\x00(\d+)\x00/g, (_, i) => tokens[+i]);

  return s;
}

// JSON syntax highlighter for the KirGraph tab
function highlightJson(text) {
  let s = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // String values (before keys so keys get re-highlighted below)
  s = s.replace(/"([^"\\]*(\\.[^"\\]*)*)"/g, '<span class="ir-string">"$1"</span>');
  // JSON keys: a string followed by a colon
  s = s.replace(
    /(<span class="ir-string">"([^"]*)"<\/span>)(\s*:)/g,
    '<span class="json-key">"$2"</span>$3',
  );
  // Numbers
  s = s.replace(/\b(-?\d+(\.\d+)?([eE][+-]?\d+)?)\b/g, '<span class="ir-number">$1</span>');
  // Booleans / null
  s = s.replace(/\b(true|false|null)\b/g, '<span class="ir-literal">$1</span>');

  return s;
}

const highlightedIR = computed(() =>
  activeTab.value === 'kirgraph'
    ? highlightJson(kirgraphJson.value)
    : highlight(irText.value),
);

// ---- Copy to clipboard ----
async function copyToClipboard() {
  const text = activeTab.value === 'kirgraph' ? kirgraphJson.value : irText.value;
  try {
    await navigator.clipboard.writeText(text);
    const label = activeTab.value === 'kirgraph' ? 'KirGraph JSON' : 'IR';
    ElMessage({ message: `${label} copied to clipboard.`, type: 'success', duration: 1500 });
  } catch {
    ElMessage({ message: 'Copy failed — check browser permissions.', type: 'error', duration: 2000 });
  }
}

// ---- Execute with WebSocket live output ----
const isExecuting = ref(false);
const execOutput = ref('');
const execError = ref('');
const execVariables = ref({});
const showExecOutput = ref(false);

// Active WS cancel handle — allows stopping mid-run
let _cancelExec = null;

function execute() {
  if (isExecuting.value) {
    // Cancel the current run
    _cancelExec?.();
    _cancelExec = null;
    isExecuting.value = false;
    return;
  }

  // Build kirgraph from the current canvas — let the backend compile it
  // (this path is more reliable than the frontend compiler for execution)
  const kirgraph = graphToKirgraph(graph.nodeList, graph.connectionList);
  if (!graph.nodeList.length) {
    ElMessage({ message: 'Graph is empty — nothing to execute.', type: 'warning', duration: 2000 });
    return;
  }

  isExecuting.value = true;
  execOutput.value = '';
  execError.value = '';
  execVariables.value = {};
  showExecOutput.value = true;

  const { cancel, ws } = executeKirgraphStreaming(kirgraph, {
    onStarted() {
      execOutput.value += '[ Execution started ]\n';
    },
    onCompiled(kirSrc) {
      // Silently received — available for debugging if needed
    },
    onOutput(text) {
      execOutput.value += text;
      // Ensure output ends with newline for readability
      if (text && !text.endsWith('\n')) execOutput.value += '\n';
    },
    onError(msg) {
      execError.value = msg;
      isExecuting.value = false;
    },
    onVariable(name, value) {
      execVariables.value = { ...execVariables.value, [name]: value };
    },
    onCompleted(variables) {
      execVariables.value = variables;
      isExecuting.value = false;
      _cancelExec = null;
      ElMessage({ message: 'Execution completed.', type: 'success', duration: 1500 });
    },
  });

  _cancelExec = cancel;

  ws.onerror = () => {
    execError.value = 'WebSocket error — is the backend running on port 48888?';
    isExecuting.value = false;
    _cancelExec = null;
  };

  ws.onclose = (event) => {
    isExecuting.value = false;
    _cancelExec = null;
    if (event.code !== 1000 && !execError.value) {
      execError.value = `Connection closed unexpectedly (code ${event.code}).`;
    }
  };
}

// ---- Toggle KIR mode ----
function toggleMode() {
  mode.value = mode.value === 'controlflow' ? 'dataflow' : 'controlflow';
}
</script>

<template>
  <div class="ir-root">

    <!-- Toolbar -->
    <div class="ir-toolbar">
      <span class="ir-toolbar-label">
        <span class="i-carbon-code ir-toolbar-icon" />
        IR Output
      </span>
      <span class="ir-stats">
        {{ graph.nodeList.length }} node{{ graph.nodeList.length !== 1 ? 's' : '' }},
        {{ graph.connectionList.length }} connection{{ graph.connectionList.length !== 1 ? 's' : '' }}
      </span>
      <div class="ir-toolbar-actions">
        <!-- Tab switcher -->
        <div class="ir-tab-group" role="tablist">
          <button
            class="ir-tab-btn"
            :class="{ active: activeTab === 'kir' }"
            role="tab"
            :aria-selected="activeTab === 'kir'"
            title="Show compiled KIR output"
            @click="activeTab = 'kir'"
          >KIR</button>
          <button
            class="ir-tab-btn"
            :class="{ active: activeTab === 'kirgraph' }"
            role="tab"
            :aria-selected="activeTab === 'kirgraph'"
            title="Show .kirgraph JSON (L1 IR)"
            @click="activeTab = 'kirgraph'"
          >KirGraph JSON</button>
        </div>

        <!-- KIR mode toggle (only shown on KIR tab) -->
        <button
          v-if="activeTab === 'kir'"
          class="ir-action-btn ir-mode-btn"
          :title="`Mode: ${mode} (click to toggle)`"
          @click="toggleMode"
        >
          {{ mode === 'controlflow' ? 'CF' : 'DF' }}
        </button>

        <!-- Compiler source indicator (KIR tab only) -->
        <span
          v-if="activeTab === 'kir'"
          class="ir-compiler-badge"
          :class="`ir-compiler-badge--${compilerSource}`"
          :title="compilerSource === 'python' ? 'Compiled by Python (KirGraphCompiler)' : compilerSource === 'loading' ? 'Pyodide loading — showing JS fallback' : 'Compiled by JS fallback compiler'"
        >
          {{ compilerSource === 'python' ? 'Py' : compilerSource === 'loading' ? '...' : 'JS' }}
        </span>

        <button class="ir-action-btn" title="Copy to clipboard" @click="copyToClipboard">
          <span class="i-carbon-copy" />
          Copy
        </button>
        <button
          class="ir-action-btn ir-action-btn--exec"
          :class="{ 'ir-action-btn--exec-running': isExecuting }"
          :title="isExecuting ? 'Click to cancel execution' : 'Execute graph on backend'"
          @click="execute"
        >
          <span :class="isExecuting ? 'i-carbon-stop-filled' : 'i-carbon-play'" />
          {{ isExecuting ? 'Stop' : 'Execute' }}
        </button>
      </div>
    </div>

    <!-- Compilation errors banner (KIR tab only) -->
    <div v-if="activeTab === 'kir' && compileErrors.length > 0" class="ir-errors">
      <div v-for="(err, i) in compileErrors" :key="i" class="ir-error-line">
        {{ err }}
      </div>
    </div>

    <!-- Code display -->
    <div class="ir-code-wrapper">
      <!-- Line gutter -->
      <div class="ir-gutter" aria-hidden="true">
        <div v-for="n in lineCount" :key="n" class="ir-gutter-line">{{ n }}</div>
      </div>
      <!-- Highlighted code -->
      <pre
        class="ir-code"
        v-html="highlightedIR"
      />
    </div>

    <!-- Execution output panel -->
    <div v-if="showExecOutput" class="exec-output-panel">
      <div class="exec-output-header">
        <span class="exec-output-title">
          <span :class="isExecuting ? 'i-carbon-circle-dash exec-spin' : 'i-carbon-checkmark'" />
          {{ isExecuting ? 'Executing…' : 'Execution Output' }}
        </span>
        <button class="exec-close-btn" title="Close output" @click="showExecOutput = false">✕</button>
      </div>
      <div v-if="execError" class="exec-error">{{ execError }}</div>
      <pre class="exec-output-body">{{ execOutput || (isExecuting ? '(waiting for output…)' : '(no output)') }}</pre>
      <!-- Variable results table -->
      <div v-if="!isExecuting && Object.keys(execVariables).length > 0" class="exec-vars">
        <div class="exec-vars-title">Variables</div>
        <div
          v-for="(val, key) in execVariables"
          :key="key"
          class="exec-var-row"
        >
          <span class="exec-var-name">{{ key }}</span>
          <span class="exec-var-eq">=</span>
          <span class="exec-var-val">{{ typeof val === 'object' ? JSON.stringify(val) : String(val) }}</span>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.ir-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #11111b;
  overflow: hidden;
  font-size: 12px;
  color: #cdd6f4;
}

/* ---- Toolbar ---- */
.ir-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 12px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}

.ir-toolbar-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
}
.ir-toolbar-icon {
  font-size: 13px;
  color: #89b4fa;
}

.ir-stats {
  font-size: 11px;
  color: #45475a;
  margin-left: 4px;
}

.ir-toolbar-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.ir-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  background: transparent;
  border: 1px solid #45475a;
  border-radius: 4px;
  color: #a6adc8;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s, color 0.1s;
}
.ir-action-btn:hover:not(:disabled) {
  background: #313244;
  border-color: #585b70;
  color: #cdd6f4;
}
.ir-action-btn--exec {
  color: #a6e3a1;
  border-color: rgba(166, 227, 161, 0.4);
}
.ir-action-btn--exec:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.ir-action-btn--exec-running {
  color: #f9e2af;
  border-color: rgba(249, 226, 175, 0.5);
  animation: exec-pulse 1.2s ease-in-out infinite;
}
@keyframes exec-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.ir-mode-btn {
  font-weight: 700;
  font-size: 10px;
  letter-spacing: 0.05em;
  color: #f9e2af;
  border-color: rgba(249, 226, 175, 0.4);
  min-width: 32px;
  justify-content: center;
}
.ir-mode-btn:hover {
  background: rgba(249, 226, 175, 0.1);
  border-color: rgba(249, 226, 175, 0.6);
}

.ir-compiler-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border: 1px solid;
  cursor: default;
  min-width: 28px;
}
.ir-compiler-badge--python {
  color: #a6e3a1;
  border-color: rgba(166, 227, 161, 0.4);
  background: rgba(166, 227, 161, 0.08);
}
.ir-compiler-badge--js {
  color: #f9e2af;
  border-color: rgba(249, 226, 175, 0.4);
  background: rgba(249, 226, 175, 0.08);
}
.ir-compiler-badge--loading {
  color: #6c7086;
  border-color: rgba(108, 112, 134, 0.4);
  background: transparent;
}

/* ---- Tab group ---- */
.ir-tab-group {
  display: flex;
  border: 1px solid #45475a;
  border-radius: 4px;
  overflow: hidden;
}

.ir-tab-btn {
  padding: 3px 10px;
  background: transparent;
  border: none;
  color: #6c7086;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
  white-space: nowrap;
}
.ir-tab-btn + .ir-tab-btn {
  border-left: 1px solid #45475a;
}
.ir-tab-btn:hover:not(.active) {
  background: #313244;
  color: #a6adc8;
}
.ir-tab-btn.active {
  background: #313244;
  color: #cdd6f4;
  font-weight: 600;
}

/* ---- Errors banner ---- */
.ir-errors {
  background: rgba(243, 139, 168, 0.1);
  border-bottom: 1px solid rgba(243, 139, 168, 0.3);
  padding: 6px 14px;
  flex-shrink: 0;
}
.ir-error-line {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  color: #f38ba8;
  line-height: 1.5;
}

/* ---- Code wrapper ---- */
.ir-code-wrapper {
  flex: 1;
  display: flex;
  overflow: auto;
  min-height: 0;
}
.ir-code-wrapper::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.ir-code-wrapper::-webkit-scrollbar-track {
  background: #11111b;
}
.ir-code-wrapper::-webkit-scrollbar-thumb {
  background: #313244;
  border-radius: 3px;
}
.ir-code-wrapper::-webkit-scrollbar-thumb:hover {
  background: #45475a;
}

/* ---- Gutter ---- */
.ir-gutter {
  flex-shrink: 0;
  padding: 10px 0;
  background: #11111b;
  border-right: 1px solid #1e1e2e;
  user-select: none;
  text-align: right;
}
.ir-gutter-line {
  padding: 0 10px 0 14px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.65;
  color: #313244;
  min-height: 1.65em;
}

/* ---- Code ---- */
.ir-code {
  margin: 0;
  padding: 10px 14px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.65;
  color: #cdd6f4;
  background: transparent;
  white-space: pre;
  tab-size: 2;
  flex: 1;
  min-width: 0;
}

/* ---- Syntax colours ---- */
.ir-code :deep(.ir-comment) {
  color: #585b70;
  font-style: italic;
}
.ir-code :deep(.ir-directive) {
  color: #f5c2e7;
  font-weight: 700;
}
.ir-code :deep(.ir-keyword) {
  color: #cba6f7;
  font-weight: 600;
}
.ir-code :deep(.ir-label) {
  color: #89dceb;
  font-weight: 600;
}
.ir-code :deep(.ir-literal) {
  color: #fab387;
  font-weight: 600;
}
.ir-code :deep(.ir-func) {
  color: #89b4fa;
}
.ir-code :deep(.ir-var) {
  color: #a6e3a1;
}
.ir-code :deep(.ir-string) {
  color: #a6e3a1;
}
.ir-code :deep(.ir-number) {
  color: #fab387;
}
.ir-code :deep(.json-key) {
  color: #89b4fa;
}

/* ---- Execution output panel ---- */
.exec-output-panel {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-top: 1px solid #313244;
  background: #0d0d17;
  max-height: 140px;
  overflow: hidden;
}

.exec-output-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}

.exec-output-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #6c7086;
}

.exec-close-btn {
  background: transparent;
  border: none;
  color: #585b70;
  font-size: 11px;
  cursor: pointer;
  padding: 1px 4px;
  border-radius: 3px;
  line-height: 1;
  transition: color 0.1s, background 0.1s;
}
.exec-close-btn:hover {
  color: #cdd6f4;
  background: #313244;
}

.exec-error {
  padding: 4px 12px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 10px;
  color: #f38ba8;
  background: rgba(243, 139, 168, 0.08);
  border-bottom: 1px solid rgba(243, 139, 168, 0.2);
  flex-shrink: 0;
}

.exec-output-body {
  margin: 0;
  padding: 6px 12px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 10px;
  line-height: 1.6;
  color: #a6e3a1;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  flex: 1;
  min-height: 0;
}
.exec-output-body::-webkit-scrollbar {
  width: 4px;
}
.exec-output-body::-webkit-scrollbar-track {
  background: #0d0d17;
}
.exec-output-body::-webkit-scrollbar-thumb {
  background: #313244;
  border-radius: 2px;
}

@keyframes exec-spin-anim {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.exec-spin {
  display: inline-block;
  animation: exec-spin-anim 1s linear infinite;
}

/* ---- Variable results ---- */
.exec-vars {
  flex-shrink: 0;
  border-top: 1px solid #1e1e2e;
  padding: 4px 12px 6px;
  background: #0d0d17;
}

.exec-vars-title {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #45475a;
  margin-bottom: 3px;
}

.exec-var-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 10px;
  line-height: 1.6;
}

.exec-var-name {
  color: #89b4fa;
  min-width: 80px;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exec-var-eq {
  color: #585b70;
}

.exec-var-val {
  color: #a6e3a1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
</style>
