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

// ── IR Preview position: 'bottom' | 'right' ──
const irPosition = ref('bottom');

function toggleIrPosition() {
  irPosition.value = irPosition.value === 'bottom' ? 'right' : 'bottom';
}

// ── NodeDefEditor dialog ───────────────────────────────────────────────────────
const nodeDefEditorOpen = ref(false);
const nodeDefEditorTarget = ref(null);

function openNodeDefEditor(def) {
  nodeDefEditorTarget.value = def ?? null;
  nodeDefEditorOpen.value = true;
}
</script>

<template>
  <div class="editor-root" :class="{ 'ir-right': irOpen && irPosition === 'right' }">

    <!-- ── Main body ── -->
    <div class="editor-body">

      <!-- Left: Node Palette -->
      <aside class="panel panel-left">
        <div class="panel-title">Node Palette</div>
        <NodePalette @open-node-def-editor="openNodeDefEditor" />
      </aside>

      <!-- Centre: Canvas + optional bottom IR -->
      <div class="center-column">
        <main class="canvas-area">
          <EditorCanvas :zoom="zoom" @update:zoom="emit('update:zoom', $event)" />
        </main>

        <!-- IR Preview — BOTTOM position -->
        <div
          v-if="irPosition === 'bottom'"
          class="ir-preview-wrapper"
          :class="{ open: irOpen }"
        >
          <div class="ir-preview-header" @click="emit('update:irOpen', !irOpen)">
            <span>IR Preview</span>
            <span class="ir-header-actions">
              <button
                class="ir-pos-btn"
                title="Move to right side"
                @click.stop="toggleIrPosition"
              >⇥</button>
              <span class="ir-toggle-icon">{{ irOpen ? '▼' : '▲' }}</span>
            </span>
          </div>
          <div v-show="irOpen" class="ir-preview-body">
            <IrPreview />
          </div>
        </div>
      </div>

      <!-- Right: Property Panel OR IR Preview (right position) -->
      <aside class="panel panel-right">
        <template v-if="irOpen && irPosition === 'right'">
          <div class="ir-preview-header ir-preview-header--right" @click="emit('update:irOpen', !irOpen)">
            <span>IR Preview</span>
            <span class="ir-header-actions">
              <button
                class="ir-pos-btn"
                title="Move to bottom"
                @click.stop="toggleIrPosition"
              >⇤</button>
              <span class="ir-toggle-icon">✕</span>
            </span>
          </div>
          <div class="ir-preview-body ir-preview-body--right">
            <IrPreview />
          </div>
        </template>
        <template v-else>
          <div class="panel-title">Properties</div>
          <PropertyPanel />
        </template>
      </aside>

    </div>

    <!-- ── Node Def Editor dialog ── -->
    <NodeDefEditor
      v-model="nodeDefEditorOpen"
      :definition="nodeDefEditorTarget"
    />

  </div>
</template>

<style scoped>
/* ── Root layout ── */
.editor-root {
  display: flex;
  flex-direction: column;
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
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

/* When IR is on the right, give the right panel more space */
.ir-right .editor-body {
  grid-template-columns: 240px 1fr 400px;
}

/* ── Center column (canvas + optional bottom IR) ── */
.center-column {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
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
  flex-shrink: 0;
}

/* ── Canvas area ── */
.canvas-area {
  flex: 1;
  overflow: hidden;
  position: relative;
  min-height: 0;
}

/* ── IR Preview strip (bottom) ── */
.ir-preview-wrapper {
  background: #181825;
  border-top: 1px solid #313244;
  flex-shrink: 0;
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
  flex-shrink: 0;
}
.ir-preview-header:hover {
  background: #1e1e2e;
}

.ir-preview-header--right {
  border-bottom: 1px solid #313244;
}

.ir-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ir-pos-btn {
  background: none;
  border: 1px solid #45475a;
  border-radius: 3px;
  color: #6c7086;
  font-size: 10px;
  padding: 1px 6px;
  cursor: pointer;
  line-height: 1;
}
.ir-pos-btn:hover {
  background: #313244;
  color: #cdd6f4;
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

/* Right-side IR fills the panel */
.ir-preview-body--right {
  flex: 1;
  height: auto;
  border-top: none;
}
</style>
