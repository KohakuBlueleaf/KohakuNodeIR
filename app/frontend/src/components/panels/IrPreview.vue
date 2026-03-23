<script setup>
import { ref, computed, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useGraphStore } from '../../stores/graph.js';
import { compileGraph } from '../../compiler/graphToIr.js';
import { graphToKirgraph } from '../../compiler/kirgraph.js';

const graph = useGraphStore();

// ---- Panel tab: 'kir' | 'kirgraph' ----
const activeTab = ref('kir');

// ---- Compilation mode ----
const mode = ref('controlflow');

// ---- Reactive IR text ----
const irText = ref('');
const compileErrors = ref([]);

// Recompute whenever the graph changes or mode changes
watch(
  [() => graph.nodeList, () => graph.connectionList, mode],
  ([nodes, conns, m]) => {
    const { ir, errors } = compileGraph(nodes, conns, m);
    irText.value = ir;
    compileErrors.value = errors;
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
  // Escape HTML first
  let s = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Comments (# ...)
  s = s.replace(/(#[^\n]*)/g, '<span class="ir-comment">$1</span>');
  // @meta, @mode, @def directives
  s = s.replace(/(@(?:meta|mode|def|dataflow)\b)/g, '<span class="ir-directive">$1</span>');
  // Backtick-quoted namespace labels
  s = s.replace(/(`[^`]*`)/g, '<span class="ir-label">$1</span>');
  // Built-in utilities: branch, switch, jump, parallel
  s = s.replace(/\b(branch|switch|jump|parallel)\b/g, '<span class="ir-keyword">$1</span>');
  // Python-style booleans and None
  s = s.replace(/\b(True|False|None)\b/g, '<span class="ir-literal">$1</span>');
  // Namespace labels (word followed by colon at line start or after indent)
  s = s.replace(/^(\s*\w+)(:)$/gm, '<span class="ir-label">$1$2</span>');
  // String literals (double-quoted)
  s = s.replace(/"([^"\\]*(\\.[^"\\]*)*)"/g, '<span class="ir-string">"$1"</span>');
  // Numbers
  s = s.replace(/\b(\d+(\.\d+)?)\b/g, '<span class="ir-number">$1</span>');
  // Variable assignments (identifier = ...)
  s = s.replace(/^(\s*)(v_\w+)(\s*=)/gm, '$1<span class="ir-var">$2</span>$3');
  // Function call output vars in right parens — highlight variable names
  s = s.replace(/\)([\w.]+)\(/g, ')<span class="ir-func">$1</span>(');

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
const showExecOutput = ref(false);

function execute() {
  if (isExecuting.value) return;

  // Compile the current graph to KIR
  const { ir: kirSource, errors } = compileGraph(graph.nodeList, graph.connectionList, mode.value);
  if (errors.length > 0) {
    ElMessage({ message: `Cannot execute: compile errors exist.`, type: 'error', duration: 3000 });
    return;
  }
  if (!kirSource.trim()) {
    ElMessage({ message: 'Graph is empty — nothing to execute.', type: 'warning', duration: 2000 });
    return;
  }

  isExecuting.value = true;
  execOutput.value = '';
  execError.value = '';
  showExecOutput.value = true;

  // Connect WebSocket for streaming output
  const wsUrl = `ws://${window.location.hostname}:48888/api/ws/execute`;
  let ws = null;
  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    execError.value = `WebSocket connection failed: ${e.message}`;
    isExecuting.value = false;
    return;
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'output' || msg.type === 'stdout') {
        execOutput.value += msg.data ?? msg.text ?? '';
      } else if (msg.type === 'error' || msg.type === 'stderr') {
        execOutput.value += `[ERR] ${msg.data ?? msg.text ?? ''}\n`;
      } else if (msg.type === 'result') {
        if (msg.variables) {
          execOutput.value += '\n--- Variables ---\n';
          for (const [k, v] of Object.entries(msg.variables)) {
            execOutput.value += `  ${k} = ${JSON.stringify(v)}\n`;
          }
        }
      } else if (msg.type === 'done' || msg.type === 'finished') {
        isExecuting.value = false;
        ws.close();
      }
    } catch {
      // Non-JSON message — treat as raw output
      execOutput.value += event.data + '\n';
    }
  };

  ws.onerror = () => {
    execError.value = 'WebSocket error — is the backend running on port 48888?';
    isExecuting.value = false;
  };

  ws.onclose = (event) => {
    isExecuting.value = false;
    if (event.code !== 1000 && !execError.value) {
      execError.value = `Connection closed (code ${event.code}).`;
    }
  };

  ws.onopen = () => {
    // Send the KIR source once the socket is open
    fetch('/api/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kir_source: kirSource }),
    })
      .then((res) => {
        if (!res.ok) {
          return res.json().catch(() => ({ detail: res.statusText })).then((body) => {
            execError.value = `Execute failed: ${body.detail ?? body.error ?? res.statusText}`;
            isExecuting.value = false;
            ws.close();
          });
        }
        return res.json().then((body) => {
          // If backend responds synchronously (no WebSocket events):
          if (body.output !== undefined) execOutput.value += body.output;
          if (body.variables) {
            execOutput.value += '\n--- Variables ---\n';
            for (const [k, v] of Object.entries(body.variables)) {
              execOutput.value += `  ${k} = ${JSON.stringify(v)}\n`;
            }
          }
          // If no WS messages come, mark done
          if (!isExecuting.value) return;
          // Give WS a moment; if done flag never arrives we stop after a grace period
          setTimeout(() => { isExecuting.value = false; }, 10000);
        });
      })
      .catch((err) => {
        execError.value = `Network error: ${err.message}`;
        isExecuting.value = false;
        ws.close();
      });
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

        <button class="ir-action-btn" title="Copy to clipboard" @click="copyToClipboard">
          <span class="i-carbon-copy" />
          Copy
        </button>
        <button
          class="ir-action-btn ir-action-btn--exec"
          :class="{ 'ir-action-btn--exec-running': isExecuting }"
          :title="isExecuting ? 'Executing…' : 'Execute KIR on backend'"
          :disabled="isExecuting"
          @click="execute"
        >
          <span :class="isExecuting ? 'i-carbon-stop-filled' : 'i-carbon-play'" />
          {{ isExecuting ? 'Executing…' : 'Execute' }}
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
</style>
