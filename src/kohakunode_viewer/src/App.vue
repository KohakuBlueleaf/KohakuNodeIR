<script setup>
import { ref, computed } from "vue";
import ViewerCanvas from "./components/ViewerCanvas.vue";
import FileDropZone from "./components/FileDropZone.vue";

// ── Graph state ───────────────────────────────────────────────────────────────
const nodes = ref([]);
const edges = ref([]);
const loadedFilename = ref(null);

// ── Paste KIR dialog ──────────────────────────────────────────────────────────
const pasteDialogVisible = ref(false);
const pasteText = ref("");
const pasteError = ref("");

// ── File loading ──────────────────────────────────────────────────────────────
function onGraphLoaded({ nodes: n, edges: e, filename }) {
  nodes.value = n;
  edges.value = e;
  loadedFilename.value = filename ?? null;
  pasteDialogVisible.value = false;
  pasteText.value = "";
  pasteError.value = "";
}

function openFilePicker() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".kir,.kirgraph,.json";
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    const text = await file.text();
    try {
      const { detectAndParse } = await import("./parser/index.js");
      const { nodes: n, edges: e } = detectAndParse(file.name, text);
      onGraphLoaded({ nodes: n, edges: e, filename: file.name });
    } catch (err) {
      console.error("Failed to parse file:", err);
    }
  };
  input.click();
}

async function confirmPaste() {
  pasteError.value = "";
  const text = pasteText.value.trim();
  if (!text) {
    pasteError.value = "Nothing to paste.";
    return;
  }
  try {
    const { detectAndParse } = await import("./parser/index.js");
    const { nodes: n, edges: e } = detectAndParse("paste.kir", text);
    onGraphLoaded({ nodes: n, edges: e, filename: "pasted KIR" });
  } catch (err) {
    pasteError.value = `Parse error: ${err.message}`;
  }
}

// ── Info bar ──────────────────────────────────────────────────────────────────
const nodeCount = computed(() => nodes.value.length);
const edgeCount = computed(() => edges.value.length);
const dataEdgeCount = computed(
  () => edges.value.filter((e) => e.portType === "data").length
);
const ctrlEdgeCount = computed(
  () => edges.value.filter((e) => e.portType === "control").length
);
</script>

<template>
  <div class="viewer-root">
    <!-- ── Toolbar ── -->
    <header class="toolbar">
      <span class="toolbar__title">KIR Viewer</span>
      <div class="toolbar__actions">
        <el-button size="small" @click="openFilePicker">Open File</el-button>
        <el-button size="small" @click="pasteDialogVisible = true">Paste KIR</el-button>
      </div>
    </header>

    <!-- ── Canvas area ── -->
    <main class="canvas-area">
      <ViewerCanvas :nodes="nodes" :edges="edges" />
      <!-- Full-screen drop zone overlay (only shows when dragging) -->
      <FileDropZone @graph-loaded="onGraphLoaded" />
    </main>

    <!-- ── Info bar ── -->
    <footer class="info-bar">
      <template v-if="nodeCount > 0 || edgeCount > 0">
        <span class="info-bar__item">
          <span class="info-bar__label">Nodes</span>
          <span class="info-bar__value">{{ nodeCount }}</span>
        </span>
        <span class="info-bar__sep" />
        <span class="info-bar__item">
          <span class="info-bar__label">Edges</span>
          <span class="info-bar__value">{{ edgeCount }}</span>
        </span>
        <span class="info-bar__sep" />
        <span class="info-bar__item">
          <span class="info-bar__label info-bar__label--data">data</span>
          <span class="info-bar__value">{{ dataEdgeCount }}</span>
        </span>
        <span class="info-bar__sep" />
        <span class="info-bar__item">
          <span class="info-bar__label info-bar__label--ctrl">ctrl</span>
          <span class="info-bar__value">{{ ctrlEdgeCount }}</span>
        </span>
        <template v-if="loadedFilename">
          <span class="info-bar__sep" />
          <span class="info-bar__item info-bar__filename">{{ loadedFilename }}</span>
        </template>
      </template>
      <template v-else>
        <span class="info-bar__hint">Drop a .kir or .kirgraph file, or use Open File / Paste KIR</span>
      </template>
    </footer>

    <!-- ── Paste dialog ── -->
    <el-dialog
      v-model="pasteDialogVisible"
      title="Paste KIR Text"
      width="600px"
      :close-on-click-modal="true"
    >
      <el-input
        v-model="pasteText"
        type="textarea"
        :rows="16"
        placeholder="Paste .kir or .kirgraph JSON here..."
        resize="none"
        style="font-family: monospace; font-size: 12px;"
      />
      <div v-if="pasteError" class="paste-error">{{ pasteError }}</div>
      <template #footer>
        <el-button @click="pasteDialogVisible = false">Cancel</el-button>
        <el-button type="primary" @click="confirmPaste">Load</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.viewer-root {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

/* ── Toolbar ── */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  height: 44px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
  gap: 12px;
}

.toolbar__title {
  font-size: 14px;
  font-weight: 700;
  color: #cdd6f4;
  letter-spacing: 0.04em;
}

.toolbar__actions {
  display: flex;
  gap: 8px;
}

/* ── Canvas area ── */
.canvas-area {
  flex: 1;
  position: relative;
  overflow: hidden;
  min-height: 0;
}

/* ── Info bar ── */
.info-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  height: 30px;
  background: #181825;
  border-top: 1px solid #313244;
  flex-shrink: 0;
  font-size: 11px;
}

.info-bar__item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.info-bar__label {
  color: #6c7086;
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: 0.06em;
}

.info-bar__label--data { color: #89b4fa; }
.info-bar__label--ctrl { color: #fab387; }

.info-bar__value {
  color: #cdd6f4;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.info-bar__sep {
  width: 1px;
  height: 14px;
  background: #313244;
  flex-shrink: 0;
}

.info-bar__filename {
  color: #6c7086;
  font-style: italic;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 300px;
}

.info-bar__hint {
  color: #45475a;
  font-style: italic;
}

/* ── Paste error ── */
.paste-error {
  margin-top: 8px;
  font-size: 12px;
  color: #f38ba8;
}
</style>
