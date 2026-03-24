<script setup>
import { ref } from 'vue';
import EditorCanvas from './EditorCanvas.vue';
import NodePalette from '../panels/NodePalette.vue';
import PropertyPanel from '../panels/PropertyPanel.vue';
import NodeDefEditor from '../panels/NodeDefEditor.vue';
import IrPreview from '../panels/IrPreview.vue';

// ── Props / emits ──────────────────────────────────────────────────────────────
const props = defineProps({
  zoom: {
    type: Number,
    default: 1,
  },
  irOpen: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['update:zoom', 'update:irOpen']);

// ── NodeDefEditor dialog ───────────────────────────────────────────────────────
const nodeDefEditorOpen = ref(false);
const nodeDefEditorTarget = ref(null);

function openNodeDefEditor(def) {
  nodeDefEditorTarget.value = def ?? null;
  nodeDefEditorOpen.value = true;
}
</script>

<template>
  <div class="editor-root">

    <!-- ── Main body ── -->
    <div class="editor-body">

      <!-- Left: Node Palette -->
      <aside class="panel panel-left">
        <div class="panel-title">Node Palette</div>
        <NodePalette @open-node-def-editor="openNodeDefEditor" />
      </aside>

      <!-- Centre: Canvas -->
      <main class="canvas-area">
        <EditorCanvas :zoom="zoom" @update:zoom="emit('update:zoom', $event)" />
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
      <div class="ir-preview-header" @click="emit('update:irOpen', !irOpen)">
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
  grid-template-rows: 1fr auto;
  width: 100%;
  height: 100%;
  background: #11111b;
  color: #cdd6f4;
  overflow: hidden;
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

/* ── Canvas area ── */
.canvas-area {
  overflow: hidden;
  position: relative;
}

/* ── IR Preview strip ── */
.ir-preview-wrapper {
  background: #181825;
  border-top: 1px solid #313244;
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
