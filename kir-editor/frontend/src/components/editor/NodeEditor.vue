<script setup>
import { ref, computed, watch } from 'vue';
import EditorCanvas from './EditorCanvas.vue';
import NodePalette from '../panels/NodePalette.vue';
import PropertyPanel from '../panels/PropertyPanel.vue';
import NodeDefEditor from '../panels/NodeDefEditor.vue';
import IrPreview from '../panels/IrPreview.vue';
import { save, load } from '../../utils/persist.js';

const props = defineProps({
  zoom: { type: Number, default: 1 },
  irOpen: { type: Boolean, default: false },
});
const emit = defineEmits(['update:zoom', 'update:irOpen']);

// ── IR/Properties positions (persisted) ──
const irPosition = ref(load('irPosition', 'right'));
const propPosition = computed(() => irPosition.value === 'right' ? 'bottom' : 'right');

function toggleIrPosition() {
  irPosition.value = irPosition.value === 'bottom' ? 'right' : 'bottom';
  emit('update:irOpen', true);
}

watch(irPosition, (v) => save('irPosition', v));

// ── Resizable widths/heights (persisted) ──
const paletteW = ref(load('paletteW', 240));
const propRightW = ref(load('propRightW', 280));
const irRightW = ref(load('irRightW', 400));
const irBottomH = ref(load('irBottomH', 220));
const propBottomH = ref(load('propBottomH', 160));

watch(paletteW, (v) => save('paletteW', v));
watch(propRightW, (v) => save('propRightW', v));
watch(irRightW, (v) => save('irRightW', v));
watch(irBottomH, (v) => save('irBottomH', v));
watch(propBottomH, (v) => save('propBottomH', v));

// Right panel width: depends on what's on the right
const effectiveRightW = computed(() => {
  if (!props.irOpen) return propRightW.value;
  return irPosition.value === 'right' ? irRightW.value : propRightW.value;
});

// ── Drag-to-resize ──
function onResizePalette(e) { resize(e, paletteW, 'x', 160, 500, 1); }

function onResizeRight(e) {
  const target = props.irOpen && irPosition.value === 'right' ? irRightW : propRightW;
  resize(e, target, 'x', 180, 700, -1);
}

function onResizeIrBottom(e) { resize(e, irBottomH, 'y', 80, 600, -1); }
function onResizePropBottom(e) { resize(e, propBottomH, 'y', 80, 400, -1); }

function resize(e, target, axis, min, max, dir) {
  e.preventDefault();
  const start = axis === 'x' ? e.clientX : e.clientY;
  const startVal = target.value;
  const onMove = (ev) => {
    const delta = (axis === 'x' ? ev.clientX : ev.clientY) - start;
    target.value = Math.max(min, Math.min(max, startVal + delta * dir));
  };
  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  };
  document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
  document.body.style.userSelect = 'none';
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
}

// ── NodeDefEditor ──
const nodeDefEditorOpen = ref(false);
const nodeDefEditorTarget = ref(null);
function openNodeDefEditor(def) {
  nodeDefEditorTarget.value = def ?? null;
  nodeDefEditorOpen.value = true;
}
</script>

<template>
  <div class="editor-root">
    <div class="editor-body"
      :style="{ gridTemplateColumns: `${paletteW}px 1fr ${effectiveRightW}px` }">

      <!-- Left: Node Palette -->
      <aside class="panel panel-left">
        <div class="panel-title">Node Palette</div>
        <NodePalette @open-node-def-editor="openNodeDefEditor" />
        <!-- Resize handle on right edge -->
        <div class="drag-edge drag-edge--right" @pointerdown="onResizePalette" />
      </aside>

      <!-- Centre: canvas + optional bottom panel -->
      <div class="center-column">
        <main class="canvas-area">
          <EditorCanvas :zoom="zoom" @update:zoom="emit('update:zoom', $event)" />
        </main>

        <!-- IR Preview — bottom position -->
        <template v-if="irPosition === 'bottom'">
          <div class="ir-preview-wrapper" :class="{ open: irOpen }">
            <div v-if="irOpen" class="drag-edge drag-edge--top" @pointerdown="onResizeIrBottom" />
            <div class="ir-preview-header" @click="emit('update:irOpen', !irOpen)">
              <span>IR Preview</span>
              <span class="ir-header-actions">
                <button class="ir-pos-btn" title="Move IR to right (Properties goes right)"
                  @click.stop="toggleIrPosition">⇥</button>
                <span class="ir-toggle-icon">{{ irOpen ? '▼' : '▲' }}</span>
              </span>
            </div>
            <div v-show="irOpen" class="ir-preview-body" :style="{ height: irBottomH + 'px' }">
              <IrPreview />
            </div>
          </div>
        </template>

        <!-- Properties — bottom position (when IR is on the right) -->
        <template v-if="propPosition === 'bottom'">
          <div class="prop-bottom-wrapper">
            <div class="drag-edge drag-edge--top" @pointerdown="onResizePropBottom" />
            <div class="prop-bottom-header">
              <span>Properties</span>
            </div>
            <div class="prop-bottom-body" :style="{ height: propBottomH + 'px' }">
              <PropertyPanel />
            </div>
          </div>
        </template>
      </div>

      <!-- Right panel: IR (when open + right) or Properties (when IR bottom) -->
      <aside class="panel panel-right">
        <div class="drag-edge drag-edge--left" @pointerdown="onResizeRight" />

        <!-- IR Preview — right position (only when open) -->
        <template v-if="irOpen && irPosition === 'right'">
          <div class="ir-preview-header ir-preview-header--right" @click="emit('update:irOpen', !irOpen)">
            <span>IR Preview</span>
            <span class="ir-header-actions">
              <button class="ir-pos-btn" title="Move IR to bottom, Properties to right"
                @click.stop="toggleIrPosition">⇤</button>
              <span class="ir-toggle-icon">✕</span>
            </span>
          </div>
          <div class="ir-preview-body ir-preview-body--right">
            <IrPreview />
          </div>
        </template>

        <!-- Properties — right position (when IR is at bottom or IR is closed) -->
        <!-- When irPosition === 'right' and IR is closed, show an empty panel or placeholder -->
        <template v-else-if="irPosition === 'bottom'">
          <div class="panel-title">Properties</div>
          <PropertyPanel />
        </template>

        <!-- irPosition === 'right' but IR is closed: show IR closed state -->
        <template v-else>
          <div class="ir-preview-header ir-preview-header--right" @click="emit('update:irOpen', true)">
            <span>IR Preview</span>
            <span class="ir-header-actions">
              <button class="ir-pos-btn" title="Move IR to bottom, Properties to right"
                @click.stop="toggleIrPosition">⇤</button>
              <span class="ir-toggle-icon">▶</span>
            </span>
          </div>
          <div class="panel-empty-hint">Click header to open IR preview</div>
        </template>
      </aside>
    </div>

    <NodeDefEditor v-model="nodeDefEditorOpen" :definition="nodeDefEditorTarget" />
  </div>
</template>

<style scoped>
.editor-root {
  display: flex; flex-direction: column;
  width: 100%; height: 100%;
  background: #11111b; color: #cdd6f4; overflow: hidden;
}
.editor-body {
  display: grid; flex: 1; overflow: hidden; min-height: 0;
}
.center-column {
  display: flex; flex-direction: column; overflow: hidden; min-height: 0;
}
.panel {
  position: relative;
  display: flex; flex-direction: column;
  background: #181825; overflow: hidden;
}
.panel-left { border-right: 1px solid #313244; }
.panel-right { border-left: 1px solid #313244; }
.panel-title {
  padding: 10px 14px 8px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; color: #6c7086;
  border-bottom: 1px solid #313244; flex-shrink: 0;
}
.canvas-area { flex: 1; overflow: hidden; position: relative; min-height: 0; }

/* ── Drag edges (absolute inside parent) ── */
.drag-edge {
  position: absolute; z-index: 30;
  transition: background 0.15s;
}
.drag-edge:hover { background: rgba(137, 180, 250, 0.2); }
.drag-edge:active { background: rgba(137, 180, 250, 0.35); }
.drag-edge--right {
  top: 0; right: -3px; width: 6px; height: 100%; cursor: col-resize;
}
.drag-edge--left {
  top: 0; left: -3px; width: 6px; height: 100%; cursor: col-resize;
}
.drag-edge--top {
  top: -3px; left: 0; width: 100%; height: 6px; cursor: row-resize;
}

/* ── IR Preview ── */
.ir-preview-wrapper {
  position: relative;
  background: #181825; border-top: 1px solid #313244; flex-shrink: 0;
}
.ir-preview-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 14px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; color: #6c7086;
  cursor: pointer; user-select: none; transition: background 0.12s; flex-shrink: 0;
}
.ir-preview-header:hover { background: #1e1e2e; }
.ir-preview-header--right { border-bottom: 1px solid #313244; }
.ir-header-actions { display: flex; align-items: center; gap: 8px; }
.ir-pos-btn {
  background: none; border: 1px solid #45475a; border-radius: 3px;
  color: #6c7086; font-size: 10px; padding: 1px 6px; cursor: pointer; line-height: 1;
}
.ir-pos-btn:hover { background: #313244; color: #cdd6f4; }
.ir-toggle-icon { font-size: 10px; }
.ir-preview-body {
  overflow: hidden; display: flex; flex-direction: column;
  border-top: 1px solid #313244;
}
.ir-preview-body--right { flex: 1; height: auto; border-top: none; }

.panel-empty-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: #45475a;
  padding: 16px;
  text-align: center;
}

/* ── Properties bottom strip ── */
.prop-bottom-wrapper {
  position: relative;
  background: #181825; border-top: 1px solid #313244; flex-shrink: 0;
}
.prop-bottom-header {
  display: flex; align-items: center;
  padding: 4px 14px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; color: #6c7086;
  user-select: none; flex-shrink: 0;
}
.prop-bottom-body {
  overflow: hidden; display: flex; flex-direction: column;
}
</style>
