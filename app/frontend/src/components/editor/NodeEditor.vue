<script setup>
import { ref, computed } from 'vue';
import EditorCanvas from './EditorCanvas.vue';
import NodePalette from '../panels/NodePalette.vue';
import PropertyPanel from '../panels/PropertyPanel.vue';
import NodeDefEditor from '../panels/NodeDefEditor.vue';
import IrPreview from '../panels/IrPreview.vue';

// ── Props / emits ──────────────────────────────────────────────────────────────
const props = defineProps({
  zoom: { type: Number, default: 1 },
  irOpen: { type: Boolean, default: false },
});
const emit = defineEmits(['update:zoom', 'update:irOpen']);

// ── IR Preview position: 'bottom' | 'right' ──
const irPosition = ref('bottom');
function toggleIrPosition() {
  irPosition.value = irPosition.value === 'bottom' ? 'right' : 'bottom';
  emit('update:irOpen', true);
}

// ── Resizable panel widths/heights ──
const paletteWidth = ref(240);
const rightPanelWidth = ref(280);
const irBottomHeight = ref(220);
const irRightWidth = ref(400);

const bodyGridCols = computed(() => {
  const right = (props.irOpen && irPosition.value === 'right') ? irRightWidth.value : rightPanelWidth.value;
  return `${paletteWidth.value}px 1fr ${right}px`;
});

// ── Generic resize handler ──
function startResize(e, target, axis, min, max) {
  e.preventDefault();
  const startPos = axis === 'x' ? e.clientX : e.clientY;
  const startVal = target.value;

  function onMove(ev) {
    const delta = (axis === 'x' ? ev.clientX : ev.clientY) - startPos;
    // For left panels, moving right = bigger. For right/bottom, moving left/up = bigger.
    const dir = target === paletteWidth ? 1 : -1;
    target.value = Math.max(min, Math.min(max, startVal + delta * dir));
  }
  function onUp() {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }
  document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
  document.body.style.userSelect = 'none';
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
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
  <div class="editor-root">
    <div class="editor-body" :style="{ gridTemplateColumns: bodyGridCols }">

      <!-- Left: Node Palette -->
      <aside class="panel panel-left">
        <div class="panel-title">Node Palette</div>
        <NodePalette @open-node-def-editor="openNodeDefEditor" />
      </aside>

      <!-- Resize handle: palette ↔ canvas -->
      <div class="resize-handle resize-handle--col"
        @pointerdown="startResize($event, paletteWidth, 'x', 160, 500)" />

      <!-- Centre: Canvas + optional bottom IR -->
      <div class="center-column">
        <main class="canvas-area">
          <EditorCanvas :zoom="zoom" @update:zoom="emit('update:zoom', $event)" />
        </main>

        <!-- IR Preview — BOTTOM position -->
        <template v-if="irPosition === 'bottom'">
          <!-- Resize handle: canvas ↔ IR bottom -->
          <div v-if="irOpen" class="resize-handle resize-handle--row"
            @pointerdown="startResize($event, irBottomHeight, 'y', 100, 600)" />

          <div class="ir-preview-wrapper" :class="{ open: irOpen }">
            <div class="ir-preview-header" @click="emit('update:irOpen', !irOpen)">
              <span>IR Preview</span>
              <span class="ir-header-actions">
                <button class="ir-pos-btn" title="Move to right side"
                  @click.stop="toggleIrPosition">⇥</button>
                <span class="ir-toggle-icon">{{ irOpen ? '▼' : '▲' }}</span>
              </span>
            </div>
            <div v-show="irOpen" class="ir-preview-body" :style="{ height: irBottomHeight + 'px' }">
              <IrPreview />
            </div>
          </div>
        </template>
      </div>

      <!-- Resize handle: canvas ↔ right panel -->
      <div class="resize-handle resize-handle--col"
        @pointerdown="startResize($event, irOpen && irPosition === 'right' ? irRightWidth : rightPanelWidth, 'x', 200, 700)" />

      <!-- Right panel -->
      <aside class="panel panel-right">
        <template v-if="irOpen && irPosition === 'right'">
          <div class="ir-preview-header ir-preview-header--right" @click="emit('update:irOpen', !irOpen)">
            <span>IR Preview</span>
            <span class="ir-header-actions">
              <button class="ir-pos-btn" title="Move to bottom"
                @click.stop="toggleIrPosition">⇤</button>
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

    <NodeDefEditor v-model="nodeDefEditorOpen" :definition="nodeDefEditorTarget" />
  </div>
</template>

<style scoped>
.editor-root {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: #11111b;
  color: #cdd6f4;
  overflow: hidden;
}

.editor-body {
  display: grid;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.center-column {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.panel {
  display: flex;
  flex-direction: column;
  background: #181825;
  overflow: hidden;
}
.panel-left { border-right: 1px solid #313244; }
.panel-right { border-left: 1px solid #313244; }

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

.canvas-area {
  flex: 1;
  overflow: hidden;
  position: relative;
  min-height: 0;
}

/* ── Resize handles ── */
.resize-handle {
  flex-shrink: 0;
  background: transparent;
  z-index: 20;
  transition: background 0.15s;
}
.resize-handle:hover { background: rgba(137, 180, 250, 0.15); }
.resize-handle:active { background: rgba(137, 180, 250, 0.3); }

.resize-handle--col {
  width: 5px;
  cursor: col-resize;
  margin: 0 -2px;
}
.resize-handle--row {
  height: 5px;
  cursor: row-resize;
  margin: -2px 0;
}

/* ── IR Preview ── */
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
.ir-preview-header:hover { background: #1e1e2e; }
.ir-preview-header--right { border-bottom: 1px solid #313244; }

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
.ir-pos-btn:hover { background: #313244; color: #cdd6f4; }

.ir-toggle-icon { font-size: 10px; }

.ir-preview-body {
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-top: 1px solid #313244;
}

.ir-preview-body--right {
  flex: 1;
  height: auto;
  border-top: none;
}
</style>
