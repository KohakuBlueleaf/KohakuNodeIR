<script setup>
import { ref, computed, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useGraphStore } from '../../stores/graph.js';
import { useEditorStore } from '../../stores/editor.js';
import { useNodeRegistryStore } from '../../stores/nodeRegistry.js';

const graph = useGraphStore();
const editor = useEditorStore();
const registry = useNodeRegistryStore();

// ---- Selection state ----
const selectedCount = computed(() => editor.selectedNodeIds.size);

const singleNode = computed(() => {
  if (editor.selectedNodeIds.size !== 1) return null;
  const [id] = editor.selectedNodeIds;
  return graph.nodes.get(id) ?? null;
});

// ---- Editable local state, synced from singleNode ----
const localName = ref('');
const localCode = ref('');

// Sync local state whenever the selected node changes
watch(
  singleNode,
  node => {
    if (!node) return;
    localName.value = node.name;
    localCode.value = node.properties?.code ?? '';
  },
  { immediate: true },
);

// ---- Node type color / label ----
const TYPE_COLORS = {
  branch: '#fab387',
  merge: '#fab387',
  switch: '#fab387',
  parallel: '#fab387',
  value: '#a6e3a1',
  function: '#89b4fa',
};

function typeColor(type) {
  return TYPE_COLORS[type] ?? '#cba6f7';
}

// ---- Commit name change ----
function commitName() {
  if (!singleNode.value) return;
  const trimmed = localName.value.trim();
  if (!trimmed) {
    localName.value = singleNode.value.name;
    return;
  }
  singleNode.value.name = trimmed;
}

// ---- Commit code change ----
function commitCode() {
  if (!singleNode.value) return;
  singleNode.value.properties.code = localCode.value;
}

// ---- Value node ----
const VALUE_TYPES = ['any', 'int', 'float', 'str', 'bool', 'image', 'tensor', 'list', 'dict'];

function valueNodeType(node) {
  return node.properties?.valueType ?? 'any';
}
function valueNodeValue(node) {
  return node.properties?.value ?? '';
}
function setValueNodeType(node, t) {
  node.properties.valueType = t;
}
function setValueNodeValue(node, v) {
  node.properties.value = v;
}

// ---- Switch node: case management ----
function switchCases(node) {
  // controlPorts.outputs that start with "case"
  return node.controlPorts.outputs.filter(p => p.name.startsWith('case'));
}

function addSwitchCase(node) {
  const existing = node.controlPorts.outputs.length;
  const id = `cp-case-${Date.now()}`;
  node.controlPorts.outputs.push({ id, name: `case ${existing}`, value: '' });
}

function removeSwitchCase(node, portId) {
  const idx = node.controlPorts.outputs.findIndex(p => p.id === portId);
  if (idx !== -1) node.controlPorts.outputs.splice(idx, 1);
}

// ---- Port type options ----
const PORT_TYPES = ['any', 'int', 'float', 'str', 'bool', 'image', 'tensor', 'list', 'dict'];

// ---- Multi-select: batch delete ----
async function batchDelete() {
  try {
    await ElMessageBox.confirm(
      `Delete ${selectedCount.value} selected nodes and all their connections?`,
      'Confirm Delete',
      {
        confirmButtonText: 'Delete',
        cancelButtonText: 'Cancel',
        type: 'warning',
        customClass: 'dark-msgbox',
      },
    );
    editor.deleteSelected();
    ElMessage({ message: 'Nodes deleted.', type: 'success', duration: 1500 });
  } catch {
    // cancelled
  }
}

// ---- Single delete ----
function deleteNode() {
  if (!singleNode.value) return;
  editor.deleteSelected();
}
</script>

<template>
  <div class="prop-root">

    <!-- ── Nothing selected ── -->
    <div v-if="selectedCount === 0" class="prop-empty">
      <span class="i-carbon-select-window prop-empty-icon" />
      <p>Select a node to view its properties</p>
    </div>

    <!-- ── Multiple nodes selected ── -->
    <div v-else-if="selectedCount > 1" class="prop-multi">
      <div class="prop-section-title">Selection</div>
      <div class="prop-multi-info">
        <span class="i-carbon-assembly-cluster prop-multi-icon" />
        <span>{{ selectedCount }} nodes selected</span>
      </div>
      <div class="prop-row">
        <el-button type="danger" size="small" plain @click="batchDelete">
          <span class="i-carbon-trash-can" style="margin-right:4px" />
          Delete All
        </el-button>
      </div>
    </div>

    <!-- ── Single node selected ── -->
    <div v-else-if="singleNode" class="prop-scroll">

      <!-- Header: name + type badge -->
      <div class="prop-header">
        <el-input
          v-model="localName"
          size="small"
          class="prop-name-input"
          @blur="commitName"
          @keydown.enter.prevent="commitName"
        />
        <span
          class="prop-type-badge"
          :style="{ background: typeColor(singleNode.type) + '22', color: typeColor(singleNode.type), borderColor: typeColor(singleNode.type) + '55' }"
        >
          {{ singleNode.type }}
        </span>
      </div>

      <!-- ── Value node ── -->
      <template v-if="singleNode.type === 'value'">
        <div class="prop-section-title">Value</div>
        <div class="prop-row prop-row-labeled">
          <span class="prop-label">Type</span>
          <el-select
            :model-value="valueNodeType(singleNode)"
            size="small"
            class="prop-select"
            @update:model-value="v => setValueNodeType(singleNode, v)"
          >
            <el-option v-for="t in VALUE_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="prop-row prop-row-labeled">
          <span class="prop-label">Value</span>
          <el-input
            :model-value="valueNodeValue(singleNode)"
            size="small"
            placeholder="literal value"
            class="prop-input"
            @update:model-value="v => setValueNodeValue(singleNode, v)"
          />
        </div>
      </template>

      <!-- ── Branch node ── -->
      <template v-else-if="singleNode.type === 'branch'">
        <div class="prop-section-title">Condition Port</div>
        <div class="prop-port-info">
          <span class="i-carbon-data-vis-1 prop-port-icon" style="color:#89b4fa" />
          <span class="prop-port-name">condition</span>
          <span class="prop-port-type-badge">bool</span>
        </div>
        <div class="prop-section-title" style="margin-top:10px">Control Outputs</div>
        <div v-for="port in singleNode.controlPorts.outputs" :key="port.id" class="prop-port-info">
          <span class="i-carbon-flow prop-port-icon" style="color:#fab387" />
          <span class="prop-port-name">{{ port.name }}</span>
        </div>
      </template>

      <!-- ── Switch node ── -->
      <template v-else-if="singleNode.type === 'switch'">
        <div class="prop-section-title">
          Cases
          <button class="prop-add-btn" @click="addSwitchCase(singleNode)">
            <span class="i-carbon-add" /> Add Case
          </button>
        </div>
        <div v-if="switchCases(singleNode).length === 0" class="prop-empty-hint">
          No cases defined
        </div>
        <div
          v-for="(port, idx) in switchCases(singleNode)"
          :key="port.id"
          class="prop-switch-case"
        >
          <span class="prop-case-index">{{ idx }}</span>
          <el-input
            v-model="port.name"
            size="small"
            class="prop-case-input"
            placeholder="case label"
          />
          <button class="prop-remove-btn" @click="removeSwitchCase(singleNode, port.id)">
            <span class="i-carbon-close" />
          </button>
        </div>
      </template>

      <!-- ── Function / user-defined node ── -->
      <template v-else-if="singleNode.type === 'function' || singleNode.properties?.code !== undefined">
        <!-- Input ports -->
        <div class="prop-section-title">
          Input Ports
          <span class="prop-section-count">{{ singleNode.dataPorts.inputs.length }}</span>
        </div>
        <div v-if="singleNode.dataPorts.inputs.length === 0" class="prop-empty-hint">
          No data inputs
        </div>
        <div
          v-for="port in singleNode.dataPorts.inputs"
          :key="port.id"
          class="prop-port-row"
        >
          <span class="i-carbon-arrow-right prop-port-dir-icon" style="color:#89b4fa" />
          <el-input v-model="port.name" size="small" class="prop-port-name-input" placeholder="name" />
          <el-select v-model="port.dataType" size="small" class="prop-port-type-select">
            <el-option v-for="t in PORT_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </div>

        <!-- Output ports -->
        <div class="prop-section-title" style="margin-top:10px">
          Output Ports
          <span class="prop-section-count">{{ singleNode.dataPorts.outputs.length }}</span>
        </div>
        <div v-if="singleNode.dataPorts.outputs.length === 0" class="prop-empty-hint">
          No data outputs
        </div>
        <div
          v-for="port in singleNode.dataPorts.outputs"
          :key="port.id"
          class="prop-port-row"
        >
          <span class="i-carbon-arrow-left prop-port-dir-icon" style="color:#a6e3a1" />
          <el-input v-model="port.name" size="small" class="prop-port-name-input" placeholder="name" />
          <el-select v-model="port.dataType" size="small" class="prop-port-type-select">
            <el-option v-for="t in PORT_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </div>

        <!-- Python code -->
        <div class="prop-section-title" style="margin-top:10px">Python Code</div>
        <textarea
          v-model="localCode"
          class="prop-code-area"
          spellcheck="false"
          @blur="commitCode"
        />
      </template>

      <!-- ── Generic / merge / parallel ── -->
      <template v-else>
        <div class="prop-section-title">Control Inputs</div>
        <div v-if="singleNode.controlPorts.inputs.length === 0" class="prop-empty-hint">None</div>
        <div
          v-for="port in singleNode.controlPorts.inputs"
          :key="port.id"
          class="prop-port-info"
        >
          <span class="i-carbon-flow prop-port-icon" style="color:#fab387" />
          <span class="prop-port-name">{{ port.name }}</span>
        </div>
        <div class="prop-section-title" style="margin-top:8px">Control Outputs</div>
        <div v-if="singleNode.controlPorts.outputs.length === 0" class="prop-empty-hint">None</div>
        <div
          v-for="port in singleNode.controlPorts.outputs"
          :key="port.id"
          class="prop-port-info"
        >
          <span class="i-carbon-flow prop-port-icon" style="color:#fab387" />
          <span class="prop-port-name">{{ port.name }}</span>
        </div>
      </template>

      <!-- ── Debug: position / size ── -->
      <div class="prop-section-title prop-section-debug">Debug</div>
      <div class="prop-debug-grid">
        <span class="prop-debug-label">X</span>
        <span class="prop-debug-value">{{ singleNode.x }}</span>
        <span class="prop-debug-label">Y</span>
        <span class="prop-debug-value">{{ singleNode.y }}</span>
        <span class="prop-debug-label">W</span>
        <span class="prop-debug-value">{{ singleNode.width }}</span>
        <span class="prop-debug-label">H</span>
        <span class="prop-debug-value">{{ singleNode.height }}</span>
      </div>

      <!-- ── Delete ── -->
      <div class="prop-delete-row">
        <el-button type="danger" size="small" plain style="width:100%" @click="deleteNode">
          <span class="i-carbon-trash-can" style="margin-right:4px" />
          Delete Node
        </el-button>
      </div>

    </div>
  </div>
</template>

<style scoped>
.prop-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #181825;
  overflow: hidden;
  font-size: 12px;
  color: #cdd6f4;
}

/* ---- Empty / multi states ---- */
.prop-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #45475a;
  padding: 20px;
  text-align: center;
}
.prop-empty-icon {
  font-size: 28px;
}
.prop-empty p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}

.prop-multi {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.prop-multi-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #a6adc8;
  font-size: 13px;
}
.prop-multi-icon {
  font-size: 16px;
  color: #89b4fa;
}

/* ---- Single node scroll container ---- */
.prop-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding-bottom: 16px;
}
.prop-scroll::-webkit-scrollbar {
  width: 4px;
}
.prop-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.prop-scroll::-webkit-scrollbar-thumb {
  background: #313244;
  border-radius: 2px;
}
.prop-scroll::-webkit-scrollbar-thumb:hover {
  background: #45475a;
}

/* ---- Header: name + badge ---- */
.prop-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 10px 6px;
  border-bottom: 1px solid #313244;
}

.prop-name-input {
  flex: 1;
  min-width: 0;
}
.prop-name-input :deep(.el-input__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 4px;
}
.prop-name-input :deep(.el-input__wrapper:hover),
.prop-name-input :deep(.el-input__wrapper.is-focus) {
  border-color: #585b70;
  box-shadow: none;
}
.prop-name-input :deep(.el-input__inner) {
  color: #cdd6f4;
  font-size: 13px;
  font-weight: 600;
}

.prop-type-badge {
  flex-shrink: 0;
  padding: 2px 7px;
  border-radius: 10px;
  border: 1px solid transparent;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* ---- Section titles ---- */
.prop-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
}

.prop-section-debug {
  margin-top: 10px;
  border-top: 1px solid #252535;
  padding-top: 10px;
}

.prop-section-count {
  background: #313244;
  padding: 0 5px;
  border-radius: 8px;
  font-size: 10px;
}

/* ---- Generic rows ---- */
.prop-row {
  padding: 4px 10px;
}

.prop-row-labeled {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prop-label {
  flex-shrink: 0;
  width: 44px;
  color: #6c7086;
  font-size: 11px;
}

.prop-input,
.prop-select {
  flex: 1;
  min-width: 0;
}
.prop-input :deep(.el-input__wrapper),
.prop-select :deep(.el-select__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 4px;
}
.prop-input :deep(.el-input__wrapper:hover),
.prop-input :deep(.el-input__wrapper.is-focus),
.prop-select :deep(.el-select__wrapper:hover),
.prop-select :deep(.el-select__wrapper.is-focused) {
  border-color: #585b70;
  box-shadow: none;
}
.prop-input :deep(.el-input__inner),
.prop-select :deep(.el-select__selected-item) {
  color: #cdd6f4;
  font-size: 12px;
}

/* ---- Port rows ---- */
.prop-port-info {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  font-size: 12px;
}
.prop-port-icon {
  font-size: 12px;
  flex-shrink: 0;
}
.prop-port-name {
  flex: 1;
  color: #a6adc8;
}
.prop-port-type-badge {
  font-size: 10px;
  color: #6c7086;
  background: #252535;
  padding: 1px 5px;
  border-radius: 4px;
}

.prop-port-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
}
.prop-port-dir-icon {
  font-size: 12px;
  flex-shrink: 0;
}
.prop-port-name-input {
  flex: 1;
  min-width: 0;
}
.prop-port-name-input :deep(.el-input__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 4px;
  padding: 0 6px;
}
.prop-port-name-input :deep(.el-input__wrapper:hover),
.prop-port-name-input :deep(.el-input__wrapper.is-focus) {
  border-color: #585b70;
  box-shadow: none;
}
.prop-port-name-input :deep(.el-input__inner) {
  color: #cdd6f4;
  font-size: 11px;
}
.prop-port-type-select {
  width: 72px;
  flex-shrink: 0;
}
.prop-port-type-select :deep(.el-select__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 4px;
}
.prop-port-type-select :deep(.el-select__wrapper:hover),
.prop-port-type-select :deep(.el-select__wrapper.is-focused) {
  border-color: #585b70;
  box-shadow: none;
}
.prop-port-type-select :deep(.el-select__selected-item) {
  color: #cdd6f4;
  font-size: 11px;
}

/* ---- Switch cases ---- */
.prop-add-btn {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px;
  background: transparent;
  border: 1px solid #45475a;
  border-radius: 4px;
  color: #89b4fa;
  font-size: 10px;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s;
  letter-spacing: 0;
  text-transform: none;
  font-weight: 400;
}
.prop-add-btn:hover {
  background: rgba(137, 180, 250, 0.1);
  border-color: #89b4fa;
}

.prop-switch-case {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
}
.prop-case-index {
  flex-shrink: 0;
  width: 16px;
  text-align: center;
  font-size: 10px;
  color: #6c7086;
  font-weight: 700;
}
.prop-case-input {
  flex: 1;
  min-width: 0;
}
.prop-case-input :deep(.el-input__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 4px;
}
.prop-case-input :deep(.el-input__wrapper:hover),
.prop-case-input :deep(.el-input__wrapper.is-focus) {
  border-color: #585b70;
  box-shadow: none;
}
.prop-case-input :deep(.el-input__inner) {
  color: #cdd6f4;
  font-size: 12px;
}

.prop-remove-btn {
  flex-shrink: 0;
  background: transparent;
  border: none;
  color: #45475a;
  cursor: pointer;
  padding: 2px;
  border-radius: 3px;
  font-size: 13px;
  line-height: 1;
  transition: color 0.1s, background 0.1s;
  display: flex;
  align-items: center;
}
.prop-remove-btn:hover {
  color: #f38ba8;
  background: rgba(243, 139, 168, 0.1);
}

/* ---- Code area ---- */
.prop-code-area {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin: 0 0 4px;
  padding: 8px 10px;
  min-height: 140px;
  background: #11111b;
  color: #cdd6f4;
  border: 1px solid #313244;
  border-left: none;
  border-right: none;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
  tab-size: 4;
  transition: border-color 0.1s;
}
.prop-code-area:focus {
  border-color: #585b70;
}

/* ---- Empty hint ---- */
.prop-empty-hint {
  padding: 4px 10px;
  font-size: 11px;
  color: #45475a;
  font-style: italic;
}

/* ---- Debug grid ---- */
.prop-debug-grid {
  display: grid;
  grid-template-columns: 20px 1fr 20px 1fr;
  gap: 4px 8px;
  padding: 4px 10px;
}
.prop-debug-label {
  font-size: 10px;
  color: #6c7086;
  font-weight: 700;
  text-align: right;
  padding-top: 1px;
}
.prop-debug-value {
  font-size: 11px;
  color: #585b70;
  font-family: ui-monospace, monospace;
}

/* ---- Delete row ---- */
.prop-delete-row {
  padding: 12px 10px 4px;
  border-top: 1px solid #252535;
  margin-top: 12px;
}

/* ---- Element Plus dark overrides (dropdown) ---- */
:deep(.el-select-dropdown) {
  background: #1e1e2e;
  border: 1px solid #313244;
}
:deep(.el-select-dropdown__item) {
  color: #cdd6f4;
  font-size: 12px;
}
:deep(.el-select-dropdown__item.is-hovering) {
  background: #313244;
}
:deep(.el-select-dropdown__item.is-selected) {
  color: #89b4fa;
  background: rgba(137, 180, 250, 0.1);
}
</style>
