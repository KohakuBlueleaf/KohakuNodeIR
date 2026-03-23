<script setup>
import { ref, computed, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useGraphStore } from '../../stores/graph.js';
import { compileGraph } from '../../compiler/graphToIr.js';

const graph = useGraphStore();

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

// ---- Line count for gutter ----
const lineCount = computed(() => irText.value.split('\n').length);

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
  s = s.replace(/(@(?:meta|mode|def)\b)/g, '<span class="ir-directive">$1</span>');
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

const highlightedIR = computed(() => highlight(irText.value));

// ---- Copy to clipboard ----
async function copyToClipboard() {
  try {
    await navigator.clipboard.writeText(irText.value);
    ElMessage({ message: 'IR copied to clipboard.', type: 'success', duration: 1500 });
  } catch {
    ElMessage({ message: 'Copy failed — check browser permissions.', type: 'error', duration: 2000 });
  }
}

// ---- Execute (stub) ----
function execute() {
  ElMessage({ message: 'Execution is not yet connected to the backend.', type: 'info', duration: 2500 });
}

// ---- Toggle mode ----
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
        <button
          class="ir-action-btn ir-mode-btn"
          :title="`Mode: ${mode} (click to toggle)`"
          @click="toggleMode"
        >
          {{ mode === 'controlflow' ? 'CF' : 'DF' }}
        </button>
        <button class="ir-action-btn" title="Copy IR to clipboard" @click="copyToClipboard">
          <span class="i-carbon-copy" />
          Copy
        </button>
        <button
          class="ir-action-btn ir-action-btn--exec"
          title="Execute (not yet connected)"
          disabled
          @click="execute"
        >
          <span class="i-carbon-play" />
          Execute
        </button>
      </div>
    </div>

    <!-- Compilation errors banner -->
    <div v-if="compileErrors.length > 0" class="ir-errors">
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
  opacity: 0.35;
  cursor: not-allowed;
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
</style>
