<script setup>
import { ref } from 'vue';
import NodeEditor from './components/editor/NodeEditor.vue';
import BlockCanvas from './components/blocks/BlockCanvas.vue';
import Toolbar from './components/editor/Toolbar.vue';

// ── View mode ──────────────────────────────────────────────────────────────────
// 'graph' = node graph editor, 'blocks' = Scratch-style block view
const viewMode = ref('graph');

// ── Shared zoom (passed into whichever view is visible) ────────────────────────
const zoom = ref(1);

// ── IR preview open state (NodeEditor owns the panel; Toolbar triggers it) ────
const irOpen = ref(false);
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
