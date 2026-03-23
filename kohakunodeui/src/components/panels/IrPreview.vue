<script setup>
import { ref, computed, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useGraphStore } from '../../stores/graph.js';

const graph = useGraphStore();

// ---- IR generation (placeholder until the real compiler arrives) ----

/**
 * Build a placeholder .kir text from the current graph state.
 * The actual graph->IR compiler will replace this function later.
 */
function generateIR(nodeList, connectionList) {
  if (nodeList.length === 0) {
    return '; (empty graph)\n';
  }

  const lines = [];

  lines.push('; KohakuNodeIR — .kir intermediate representation');
  lines.push(`; Generated: ${new Date().toISOString()}`);
  lines.push(`; Nodes: ${nodeList.length}   Connections: ${connectionList.length}`);
  lines.push('');

  // Declarations
  lines.push('; ── Node declarations ──────────────────────────');
  for (const node of nodeList) {
    const dataIn = node.dataPorts.inputs.map(p => `${p.name}:${p.dataType ?? 'any'}`).join(', ');
    const dataOut = node.dataPorts.outputs.map(p => `${p.name}:${p.dataType ?? 'any'}`).join(', ');
    const ctrlIn = node.controlPorts.inputs.map(p => p.name).join(', ');
    const ctrlOut = node.controlPorts.outputs.map(p => p.name).join(', ');

    lines.push(`node %${node.id.replace(/-/g, '_')} {`);
    lines.push(`  type     = "${node.type}"`);
    lines.push(`  name     = "${node.name}"`);
    if (dataIn)  lines.push(`  data_in  = [${dataIn}]`);
    if (dataOut) lines.push(`  data_out = [${dataOut}]`);
    if (ctrlIn)  lines.push(`  ctrl_in  = [${ctrlIn}]`);
    if (ctrlOut) lines.push(`  ctrl_out = [${ctrlOut}]`);
    if (node.properties?.code) {
      const escaped = node.properties.code.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
      lines.push(`  code     = """\n${node.properties.code.split('\n').map(l => '    ' + l).join('\n')}\n  """`);
    }
    if (node.type === 'value' && node.properties?.value !== undefined) {
      lines.push(`  value    = ${JSON.stringify(node.properties.value)}`);
    }
    lines.push(`}`);
    lines.push('');
  }

  // Connections
  if (connectionList.length > 0) {
    lines.push('; ── Connections ─────────────────────────────────');
    for (const conn of connectionList) {
      const fromId = conn.fromNodeId.replace(/-/g, '_');
      const toId = conn.toNodeId.replace(/-/g, '_');
      const portType = conn.portType === 'control' ? '~>' : '->';
      lines.push(
        `connect %${fromId}.${conn.fromPortId} ${portType} %${toId}.${conn.toPortId}`
      );
    }
    lines.push('');
  }

  lines.push('; ── End of IR ────────────────────────────────────');

  return lines.join('\n');
}

// ---- Reactive IR text ----
const irText = ref('');

// Recompute whenever the graph changes
watch(
  [() => graph.nodeList, () => graph.connectionList],
  ([nodes, conns]) => {
    irText.value = generateIR(nodes, conns);
  },
  { immediate: true, deep: true },
);

// ---- Line count for gutter ----
const lineCount = computed(() => irText.value.split('\n').length);

// ---- Syntax highlight ----
// Simple regex-based highlighter — no external dep needed
function highlight(text) {
  // Escape HTML first
  let s = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Comments (;...)
  s = s.replace(/(;[^\n]*)/g, '<span class="ir-comment">$1</span>');
  // Keywords: node, connect, type, name, data_in, data_out, ctrl_in, ctrl_out, code, value
  s = s.replace(/\b(node|connect|type|name|data_in|data_out|ctrl_in|ctrl_out|code|value)\b/g,
    '<span class="ir-keyword">$1</span>');
  // Port type arrows
  s = s.replace(/(-&gt;|~&gt;)/g, '<span class="ir-arrow">$1</span>');
  // Node references (%id)
  s = s.replace(/(%[a-z0-9_]+)/g, '<span class="ir-ref">$1</span>');
  // String literals
  s = s.replace(/"([^"\\]*(\\.[^"\\]*)*)"/g, '<span class="ir-string">"$1"</span>');
  // Numbers
  s = s.replace(/\b(\d+(\.\d+)?)\b/g, '<span class="ir-number">$1</span>');
  // Port type annotations e.g. :int :any
  s = s.replace(/:([a-z]+)/g, ':<span class="ir-type">$1</span>');

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
.ir-code :deep(.ir-keyword) {
  color: #cba6f7;
  font-weight: 600;
}
.ir-code :deep(.ir-arrow) {
  color: #fab387;
  font-weight: 700;
}
.ir-code :deep(.ir-ref) {
  color: #89b4fa;
}
.ir-code :deep(.ir-string) {
  color: #a6e3a1;
}
.ir-code :deep(.ir-number) {
  color: #fab387;
}
.ir-code :deep(.ir-type) {
  color: #f9e2af;
}
</style>
