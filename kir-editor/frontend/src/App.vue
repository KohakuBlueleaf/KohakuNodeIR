<script setup>
import { ref, watch, onMounted, nextTick } from 'vue';
import NodeEditor from './components/editor/NodeEditor.vue';
import BlockCanvas from './components/blocks/BlockCanvas.vue';
import KirCodeEditor from './components/editor/KirCodeEditor.vue';
import Toolbar from './components/editor/Toolbar.vue';
import { save, load } from './utils/persist.js';
import { initWasm } from './parser/wasmParser.js';

// ── View mode (persisted) ──
const viewMode = ref(load('viewMode', 'graph'));
const codeEditorRef = ref(null);
let prevViewMode = viewMode.value;
watch(viewMode, (v) => {
  save('viewMode', v);
  // When switching away from code view, sync editor→graph
  if (prevViewMode === 'code' && v !== 'code') {
    codeEditorRef.value?.onDeactivate();
  }
  // When switching to code view, load graph into editor
  if (v === 'code') nextTick(() => codeEditorRef.value?.refreshFromGraph());
  prevViewMode = v;
});

// ── Shared zoom ──
const zoom = ref(1);

// ── IR preview open state (persisted) ──
const irOpen = ref(load('irOpen', false));
watch(irOpen, (v) => save('irOpen', v));

// ── Init WASM on startup ──
onMounted(() => { initWasm(); });
</script>

<template>
  <div class="app-root">

    <!-- ── Shared toolbar ── -->
    <Toolbar
      :zoom="zoom"
      :view-mode="viewMode"
      @update:zoom="zoom = $event"
      @open-ir-preview="irOpen = true"
    />

    <!-- ── View mode tab bar ── -->
    <div class="view-switcher">
      <button
        class="view-btn"
        :class="{ 'view-btn--active': viewMode === 'graph' }"
        title="Node Graph view"
        @click="viewMode = 'graph'"
      >
        <span class="view-btn-icon">&#x25A6;</span>
        Node Graph
      </button>
      <button
        class="view-btn"
        :class="{ 'view-btn--active': viewMode === 'blocks' }"
        title="Scratch-style Blocks view"
        @click="viewMode = 'blocks'"
      >
        <span class="view-btn-icon">&#x2BC1;</span>
        Blocks
      </button>
      <button
        class="view-btn"
        :class="{ 'view-btn--active': viewMode === 'code' }"
        title="KIR code editor"
        @click="viewMode = 'code'"
      >
        <span class="view-btn-icon">&#x2774;</span>
        Code
      </button>
    </div>

    <!-- ── Views ── -->
    <div class="view-area">
      <NodeEditor
        v-show="viewMode === 'graph'"
        :zoom="zoom"
        :ir-open="irOpen"
        @update:zoom="zoom = $event"
        @update:ir-open="irOpen = $event"
      />
      <BlockCanvas
        v-show="viewMode === 'blocks'"
        :zoom="zoom"
        @update:zoom="zoom = $event"
      />
      <KirCodeEditor
        ref="codeEditorRef"
        v-show="viewMode === 'code'"
      />
    </div>

  </div>
</template>

<style>
/* Global reset */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body, #app {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #11111b;
  color: #cdd6f4;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}
</style>

<style scoped>
.app-root {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

/* ── View mode tab bar ── */
.view-switcher {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 10px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
  z-index: 100;
}

.view-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: #6c7086;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.12s, background 0.12s, border-color 0.12s;
  user-select: none;
}

.view-btn:hover {
  color: #cdd6f4;
  background: #313244;
  border-color: #45475a;
}

.view-btn--active {
  color: #cdd6f4;
  background: #313244;
  border-color: #89b4fa;
}

.view-btn-icon {
  font-size: 12px;
  opacity: 0.8;
}

/* ── View area (fills remaining space) ── */
.view-area {
  flex: 1;
  overflow: hidden;
  position: relative;
  min-height: 0;
}

/* Both views fill the entire area; v-show controls visibility */
.view-area > * {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
</style>
