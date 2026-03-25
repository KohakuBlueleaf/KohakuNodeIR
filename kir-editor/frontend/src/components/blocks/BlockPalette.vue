<script setup>
// BlockPalette.vue — sidebar listing all available block types grouped by category.
// Drag a palette item onto the BlockCanvas to create a new node.

import { computed, ref } from "vue";
import { useNodeRegistryStore } from "../../stores/nodeRegistry.js";

// ── Stores ─────────────────────────────────────────────────────────────────────
const registry = useNodeRegistryStore();

// ── Category ordering ─────────────────────────────────────────────────────────
const CATEGORY_ORDER = [
  "Control Flow",
  "Math",
  "Comparison",
  "String",
  "Display",
  "File",
  "Data",
  "Convert",
];

const CATEGORY_COLORS = {
  "Control Flow": "#fab387",
  Math: "#89b4fa",
  Comparison: "#f9e2af",
  String: "#a6e3a1",
  Display: "#89dceb",
  File: "#cba6f7",
  Data: "#a6e3a1",
  Convert: "#74c7ec",
};

// ── Grouped definitions ───────────────────────────────────────────────────────
const grouped = computed(() => {
  const cats = registry.getCategories();
  // Sort by canonical order, then alphabetically for any extras
  const sorted = [...cats].sort((a, b) => {
    const ai = CATEGORY_ORDER.indexOf(a);
    const bi = CATEGORY_ORDER.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
  return sorted.map((cat) => ({
    name: cat,
    color: CATEGORY_COLORS[cat] ?? "#a6adc8",
    defs: registry.getNodesByCategory(cat),
  }));
});

// ── Collapse state ────────────────────────────────────────────────────────────
const collapsed = ref(new Set());

function toggleCategory(name) {
  if (collapsed.value.has(name)) {
    collapsed.value.delete(name);
  } else {
    collapsed.value.add(name);
  }
}

// ── Drag from palette ─────────────────────────────────────────────────────────
// We communicate the dragged type to BlockCanvas via a custom HTML drag payload
// so it can create the node on drop.

function onDragStart(e, typeName) {
  e.dataTransfer.effectAllowed = "copy";
  e.dataTransfer.setData("application/x-block-type", typeName);
}
</script>

<template>
  <aside class="block-palette">
    <div class="palette-title">Blocks</div>

    <div v-for="group in grouped" :key="group.name" class="palette-category">
      <!-- Category header (collapsible) -->
      <button
        class="palette-cat-header"
        :style="{ '--cat-color': group.color }"
        @click="toggleCategory(group.name)"
      >
        <span
          class="palette-cat-chevron"
          :class="{ 'is-collapsed': collapsed.has(group.name) }"
          >&#x25BC;</span
        >
        <span class="palette-cat-name">{{ group.name }}</span>
      </button>

      <!-- Block items -->
      <div v-if="!collapsed.has(group.name)" class="palette-items">
        <div
          v-for="def in group.defs"
          :key="def.type"
          class="palette-item"
          :style="{ '--item-color': group.color }"
          draggable="true"
          :title="def.description"
          @dragstart="onDragStart($event, def.type)"
        >
          <span class="palette-item-dot" />
          <span class="palette-item-name">{{ def.name }}</span>
          <span class="palette-item-type">{{ def.type }}</span>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* ── Palette sidebar ── */
.block-palette {
  width: 200px;
  min-width: 200px;
  height: 100%;
  background: #181825;
  border-right: 1px solid #313244;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
  flex-shrink: 0;
  user-select: none;
}

/* ── Title bar ── */
.palette-title {
  padding: 10px 12px 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #585b70;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}

/* ── Category group ── */
.palette-category {
  border-bottom: 1px solid #1e1e2e;
}

/* ── Category header button ── */
.palette-cat-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: color-mix(in srgb, var(--cat-color) 8%, #181825);
  border: none;
  border-bottom: 1px solid color-mix(in srgb, var(--cat-color) 20%, transparent);
  cursor: pointer;
  color: var(--cat-color);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  text-align: left;
}

.palette-cat-header:hover {
  background: color-mix(in srgb, var(--cat-color) 14%, #181825);
}

.palette-cat-chevron {
  font-size: 8px;
  opacity: 0.7;
  transition: transform 0.15s ease;
  display: inline-block;
}

.palette-cat-chevron.is-collapsed {
  transform: rotate(-90deg);
}

.palette-cat-name {
  flex: 1;
}

/* ── Block items list ── */
.palette-items {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 4px 6px;
  background: #11111b;
}

/* ── Single palette item ── */
.palette-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
  border: 1px solid transparent;
  background: color-mix(in srgb, var(--item-color) 8%, #1e1e2e);
  cursor: grab;
  font-size: 11px;
  color: #cdd6f4;
  transition:
    background 0.1s,
    border-color 0.1s;
}

.palette-item:hover {
  background: color-mix(in srgb, var(--item-color) 16%, #1e1e2e);
  border-color: color-mix(in srgb, var(--item-color) 35%, transparent);
}

.palette-item:active {
  cursor: grabbing;
  background: color-mix(in srgb, var(--item-color) 22%, #1e1e2e);
}

/* Colored dot to echo the category */
.palette-item-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--item-color);
  flex-shrink: 0;
  opacity: 0.85;
}

.palette-item-name {
  flex: 1;
  font-weight: 600;
  color: color-mix(in srgb, var(--item-color) 80%, #cdd6f4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.palette-item-type {
  font-size: 9px;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  color: #585b70;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60px;
}
</style>
