<script setup>
import { ref, computed } from "vue";
import { useNodeRegistryStore } from "../../stores/nodeRegistry.js";
import { useGraphStore } from "../../stores/graph.js";
import { useEditorStore } from "../../stores/editor.js";

const registry = useNodeRegistryStore();
const graph = useGraphStore();
const editor = useEditorStore();

// ---- Search ----
const searchQuery = ref("");

// ---- Node def editor dialog ----
const emit = defineEmits(["open-node-def-editor"]);

// ---- Category ordering ----
const CATEGORY_ORDER = ["Control Flow", "Data", "User Defined"];

// ---- Category icons ----
const CATEGORY_ICONS = {
  "Control Flow": "i-carbon-flow",
  Data: "i-carbon-data-base",
  "User Defined": "i-carbon-function",
};

// ---- Node type icons ----
const NODE_ICONS = {
  branch: "i-carbon-branch",
  merge: "i-carbon-flow-stream",
  switch: "i-carbon-switcher",
  parallel: "i-carbon-parallel-processing",
  value: "i-carbon-string-integer",
};

function nodeIcon(type) {
  return NODE_ICONS[type] ?? "i-carbon-cube";
}

// ---- Filtered & grouped definitions ----
const groupedDefinitions = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  const all = registry.allDefinitions;

  const filtered = q
    ? all.filter(
        (d) =>
          d.name.toLowerCase().includes(q) ||
          d.type.toLowerCase().includes(q) ||
          d.category.toLowerCase().includes(q),
      )
    : all;

  // Build a Map: category -> definitions[]
  const groups = new Map();
  for (const def of filtered) {
    if (!groups.has(def.category)) groups.set(def.category, []);
    groups.get(def.category).push(def);
  }

  // Sort categories: known order first, then alphabetical remainder
  const sorted = Array.from(groups.entries()).sort(([a], [b]) => {
    const ai = CATEGORY_ORDER.indexOf(a);
    const bi = CATEGORY_ORDER.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });

  return sorted; // [ [categoryName, [defs...]], ... ]
});

// ---- Collapsed categories ----
const collapsedCategories = ref(new Set());
function toggleCategory(cat) {
  if (collapsedCategories.value.has(cat)) {
    collapsedCategories.value.delete(cat);
  } else {
    collapsedCategories.value.add(cat);
  }
}

// ---- Drag-and-drop ----
function onDragStart(event, def) {
  event.dataTransfer.effectAllowed = "copy";
  event.dataTransfer.setData("application/x-node-type", def.type);

  // Ghost image: create a small element that matches the pill
  const ghost = document.createElement("div");
  ghost.textContent = def.name;
  ghost.style.cssText = [
    "position:fixed",
    "top:-200px",
    "left:-200px",
    "padding:4px 10px",
    "background:#313244",
    "color:#cdd6f4",
    "border:1px solid #45475a",
    "border-radius:6px",
    "font-size:12px",
    "font-family:inherit",
    "pointer-events:none",
    "white-space:nowrap",
  ].join(";");
  document.body.appendChild(ghost);
  event.dataTransfer.setDragImage(
    ghost,
    ghost.offsetWidth / 2,
    ghost.offsetHeight / 2,
  );
  // Clean up after the drag starts
  requestAnimationFrame(() => document.body.removeChild(ghost));
}

// ---- Double-click user-defined node to open editor ----
function onDblClick(def) {
  if (def.category === "User Defined") {
    emit("open-node-def-editor", def);
  }
}
</script>

<template>
  <div class="palette-root">
    <!-- Search -->
    <div class="palette-search">
      <el-input
        v-model="searchQuery"
        placeholder="Search nodes..."
        clearable
        size="small"
        class="palette-search-input"
      >
        <template #prefix>
          <span class="i-carbon-search palette-search-icon" />
        </template>
      </el-input>
    </div>

    <!-- Node groups -->
    <div class="palette-scroll">
      <div v-if="groupedDefinitions.length === 0" class="palette-empty">
        No nodes match "{{ searchQuery }}"
      </div>

      <div
        v-for="[category, defs] in groupedDefinitions"
        :key="category"
        class="palette-group"
      >
        <!-- Category header -->
        <button class="palette-cat-header" @click="toggleCategory(category)">
          <span
            :class="[
              'palette-cat-icon',
              CATEGORY_ICONS[category] ?? 'i-carbon-folder',
            ]"
          />
          <span class="palette-cat-name">{{ category }}</span>
          <span class="palette-cat-count">{{ defs.length }}</span>
          <span
            class="palette-cat-chevron"
            :class="
              collapsedCategories.has(category)
                ? 'i-carbon-chevron-right'
                : 'i-carbon-chevron-down'
            "
          />
        </button>

        <!-- Node pills -->
        <div v-show="!collapsedCategories.has(category)" class="palette-items">
          <div
            v-for="def in defs"
            :key="def.type"
            class="palette-item"
            draggable="true"
            :title="def.description"
            @dragstart="onDragStart($event, def)"
            @dblclick="onDblClick(def)"
          >
            <span :class="['palette-item-icon', nodeIcon(def.type)]" />
            <span class="palette-item-name">{{ def.name }}</span>
            <span
              v-if="def.category === 'User Defined'"
              class="palette-item-edit-hint"
            >
              dbl-click to edit
            </span>
          </div>
        </div>
      </div>

      <!-- Add user-defined node button -->
      <div class="palette-add-btn-wrapper">
        <button
          class="palette-add-btn"
          @click="emit('open-node-def-editor', null)"
        >
          <span class="i-carbon-add" />
          New Node Type
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.palette-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #181825;
  overflow: hidden;
}

/* ---- Search ---- */
.palette-search {
  padding: 8px 10px;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}

.palette-search-input :deep(.el-input__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 5px;
}
.palette-search-input :deep(.el-input__wrapper:hover),
.palette-search-input :deep(.el-input__wrapper.is-focus) {
  border-color: #585b70;
  box-shadow: none;
}
.palette-search-input :deep(.el-input__inner) {
  color: #cdd6f4;
  font-size: 12px;
}
.palette-search-input :deep(.el-input__inner::placeholder) {
  color: #45475a;
}
.palette-search-icon {
  color: #6c7086;
  font-size: 13px;
}

/* ---- Scroll area ---- */
.palette-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding-bottom: 8px;
}
.palette-scroll::-webkit-scrollbar {
  width: 4px;
}
.palette-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.palette-scroll::-webkit-scrollbar-thumb {
  background: #313244;
  border-radius: 2px;
}
.palette-scroll::-webkit-scrollbar-thumb:hover {
  background: #45475a;
}

/* ---- Empty state ---- */
.palette-empty {
  padding: 24px 14px;
  font-size: 12px;
  color: #45475a;
  text-align: center;
}

/* ---- Category group ---- */
.palette-group {
  margin-bottom: 2px;
}

.palette-cat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 10px;
  background: transparent;
  border: none;
  color: #6c7086;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  text-align: left;
  transition:
    background 0.1s,
    color 0.1s;
  user-select: none;
}
.palette-cat-header:hover {
  background: #1e1e2e;
  color: #a6adc8;
}

.palette-cat-icon {
  font-size: 12px;
  flex-shrink: 0;
}
.palette-cat-name {
  flex: 1;
}
.palette-cat-count {
  font-size: 10px;
  background: #313244;
  padding: 0 5px;
  border-radius: 8px;
  font-weight: 600;
  letter-spacing: 0;
}
.palette-cat-chevron {
  font-size: 11px;
  flex-shrink: 0;
}

/* ---- Node items ---- */
.palette-items {
  padding: 2px 8px 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 8px;
  border-radius: 5px;
  background: #1e1e2e;
  border: 1px solid #313244;
  cursor: grab;
  font-size: 12px;
  color: #cdd6f4;
  user-select: none;
  transition:
    background 0.1s,
    border-color 0.1s,
    transform 0.1s;
  position: relative;
  overflow: hidden;
}
.palette-item:hover {
  background: #252535;
  border-color: #45475a;
}
.palette-item:active {
  cursor: grabbing;
  transform: scale(0.97);
  background: #313244;
}

.palette-item-icon {
  font-size: 14px;
  color: #89b4fa;
  flex-shrink: 0;
}

.palette-item-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.palette-item-edit-hint {
  font-size: 9px;
  color: #6c7086;
  white-space: nowrap;
  letter-spacing: 0.02em;
}

/* ---- Add button ---- */
.palette-add-btn-wrapper {
  padding: 8px 10px 4px;
}

.palette-add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 6px 0;
  background: transparent;
  border: 1px dashed #45475a;
  border-radius: 5px;
  color: #6c7086;
  font-size: 12px;
  cursor: pointer;
  transition:
    border-color 0.1s,
    color 0.1s,
    background 0.1s;
}
.palette-add-btn:hover {
  border-color: #89b4fa;
  color: #89b4fa;
  background: rgba(137, 180, 250, 0.05);
}
</style>
