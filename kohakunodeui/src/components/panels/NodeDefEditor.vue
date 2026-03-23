<script setup>
import { ref, computed, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useNodeRegistryStore } from '../../stores/nodeRegistry.js';

// ---- Props / Emits ----
const props = defineProps({
  /** The existing NodeDefinition to edit, or null to create a new one */
  definition: {
    type: Object,
    default: null,
  },
  modelValue: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['update:modelValue', 'saved']);

const registry = useNodeRegistryStore();

// ---- Port type options ----
const PORT_TYPES = ['any', 'int', 'float', 'str', 'bool', 'image', 'tensor', 'list', 'dict'];

// ---- Internal form state ----
const form = ref(makeBlankForm());

function makeBlankForm() {
  return {
    name: '',
    type: '',        // auto-derived from name if blank
    category: 'User Defined',
    description: '',
    inputs: [],
    outputs: [],
    code: '',
  };
}

let _portIdCounter = 0;
function newPortId() {
  return `dp-user-${++_portIdCounter}-${Date.now()}`;
}

function makePort(name = '', type = 'any', defaultValue = '') {
  return { id: newPortId(), name, dataType: type, defaultValue };
}

// ---- Sync when dialog opens or definition changes ----
watch(
  [() => props.modelValue, () => props.definition],
  ([open]) => {
    if (!open) return;
    if (props.definition) {
      const def = props.definition;
      form.value = {
        name: def.name,
        type: def.type,
        category: def.category,
        description: def.description ?? '',
        inputs: def.dataPorts.inputs.map(p => ({ ...p, defaultValue: p.defaultValue ?? '' })),
        outputs: def.dataPorts.outputs.map(p => ({ ...p, defaultValue: '' })),
        code: def.code ?? '',
      };
    } else {
      form.value = makeBlankForm();
    }
  },
  { immediate: true },
);

// ---- Derived type key ----
const derivedType = computed(() => {
  if (form.value.type.trim()) return form.value.type.trim().toLowerCase().replace(/\s+/g, '_');
  return form.value.name.trim().toLowerCase().replace(/\s+/g, '_') || 'custom';
});

// ---- Auto-generated function signature ----
const generatedSignature = computed(() => {
  const fnName = derivedType.value || 'my_node';
  const paramParts = form.value.inputs.map(p => {
    const safeName = p.name.trim().replace(/\s+/g, '_') || 'arg';
    return p.defaultValue !== '' && p.defaultValue !== undefined
      ? `${safeName}=${JSON.stringify(p.defaultValue)}`
      : safeName;
  });
  return `def ${fnName}(${paramParts.join(', ')}):`;
});

// ---- Existing categories for the dropdown ----
const existingCategories = computed(() => {
  const cats = registry.getCategories();
  if (!cats.includes('User Defined')) return ['User Defined', ...cats];
  return cats;
});

// ---- Input port management ----
function addInput() {
  form.value.inputs.push(makePort(`input${form.value.inputs.length + 1}`, 'any', ''));
}
function removeInput(idx) {
  form.value.inputs.splice(idx, 1);
}

// ---- Output port management ----
function addOutput() {
  form.value.outputs.push(makePort(`output${form.value.outputs.length + 1}`, 'any'));
}
function removeOutput(idx) {
  form.value.outputs.splice(idx, 1);
}

// ---- Drag-to-reorder ----
const draggingFrom = ref(null);
const draggingList = ref(null);

function onPortDragStart(list, idx) {
  draggingFrom.value = idx;
  draggingList.value = list;
}
function onPortDragOver(e, list, idx) {
  if (draggingList.value !== list) return;
  e.preventDefault();
}
function onPortDrop(list, toIdx) {
  if (draggingList.value !== list || draggingFrom.value === null) return;
  const fromIdx = draggingFrom.value;
  if (fromIdx === toIdx) return;
  const arr = list === 'inputs' ? form.value.inputs : form.value.outputs;
  const [item] = arr.splice(fromIdx, 1);
  arr.splice(toIdx, 0, item);
  draggingFrom.value = null;
  draggingList.value = null;
}
function onPortDragEnd() {
  draggingFrom.value = null;
  draggingList.value = null;
}

// ---- Node preview ---- (simple visual representation)
const previewInputs = computed(() => form.value.inputs.slice(0, 5));
const previewOutputs = computed(() => form.value.outputs.slice(0, 5));

// ---- Save ----
function handleSave() {
  const name = form.value.name.trim();
  if (!name) {
    ElMessage({ message: 'Node name is required.', type: 'warning', duration: 2000 });
    return;
  }

  const typeKey = derivedType.value;

  // Build code: if empty, use generated signature as starter
  let code = form.value.code.trim();
  if (!code) {
    const returnVars = form.value.outputs.map(p => p.name.trim().replace(/\s+/g, '_') || 'out').join(', ');
    code = `${generatedSignature.value}\n    # TODO: implement\n    ${returnVars ? `return ${returnVars}` : 'pass'}`;
  }

  const definition = {
    type: typeKey,
    name,
    category: form.value.category || 'User Defined',
    description: form.value.description,
    dataPorts: {
      inputs: form.value.inputs.map(p => ({
        id: p.id,
        name: p.name.trim() || 'in',
        dataType: p.dataType,
        defaultValue: p.defaultValue !== '' ? p.defaultValue : undefined,
      })),
      outputs: form.value.outputs.map(p => ({
        id: p.id,
        name: p.name.trim() || 'out',
        dataType: p.dataType,
      })),
    },
    controlPorts: {
      inputs: [],
      outputs: [],
    },
    code,
  };

  registry.registerNodeType(definition);
  ElMessage({ message: `Node type "${name}" saved.`, type: 'success', duration: 2000 });
  emit('saved', definition);
  emit('update:modelValue', false);
}

function handleCancel() {
  emit('update:modelValue', false);
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="definition ? `Edit Node: ${definition.name}` : 'Create Node Type'"
    width="680px"
    align-center
    destroy-on-close
    class="node-def-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="nde-root">

      <!-- ── Left column: form ── -->
      <div class="nde-form">

        <!-- Basic info -->
        <div class="nde-section-title">Identity</div>
        <div class="nde-field">
          <label class="nde-label">Name <span class="nde-required">*</span></label>
          <el-input v-model="form.name" size="small" placeholder="My Node" class="nde-input" />
        </div>
        <div class="nde-field">
          <label class="nde-label">Type key</label>
          <el-input
            v-model="form.type"
            size="small"
            :placeholder="derivedType"
            class="nde-input"
          />
          <span class="nde-hint">Auto-derived from name if blank</span>
        </div>
        <div class="nde-field">
          <label class="nde-label">Category</label>
          <el-select
            v-model="form.category"
            size="small"
            allow-create
            filterable
            class="nde-input"
          >
            <el-option
              v-for="cat in existingCategories"
              :key="cat"
              :label="cat"
              :value="cat"
            />
          </el-select>
        </div>
        <div class="nde-field">
          <label class="nde-label">Description</label>
          <el-input
            v-model="form.description"
            size="small"
            type="textarea"
            :rows="2"
            placeholder="What does this node do?"
            class="nde-input"
          />
        </div>

        <!-- Input ports -->
        <div class="nde-section-title nde-section-title-with-btn">
          Input Ports
          <button class="nde-port-add-btn" @click="addInput">
            <span class="i-carbon-add" /> Add Input
          </button>
        </div>
        <div v-if="form.inputs.length === 0" class="nde-empty-hint">No input ports</div>
        <div
          v-for="(port, idx) in form.inputs"
          :key="port.id"
          class="nde-port-row"
          draggable="true"
          @dragstart="onPortDragStart('inputs', idx)"
          @dragover="onPortDragOver($event, 'inputs', idx)"
          @drop="onPortDrop('inputs', idx)"
          @dragend="onPortDragEnd"
        >
          <span class="nde-port-drag i-carbon-draggable" />
          <span class="nde-port-index">{{ idx + 1 }}</span>
          <el-input
            v-model="port.name"
            size="small"
            placeholder="name"
            class="nde-port-name"
          />
          <el-select v-model="port.dataType" size="small" class="nde-port-type">
            <el-option v-for="t in PORT_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
          <el-input
            v-model="port.defaultValue"
            size="small"
            placeholder="default"
            class="nde-port-default"
          />
          <button class="nde-port-remove" @click="removeInput(idx)">
            <span class="i-carbon-close" />
          </button>
        </div>

        <!-- Output ports -->
        <div class="nde-section-title nde-section-title-with-btn" style="margin-top:12px">
          Output Ports
          <button class="nde-port-add-btn" @click="addOutput">
            <span class="i-carbon-add" /> Add Output
          </button>
        </div>
        <div v-if="form.outputs.length === 0" class="nde-empty-hint">No output ports</div>
        <div
          v-for="(port, idx) in form.outputs"
          :key="port.id"
          class="nde-port-row"
          draggable="true"
          @dragstart="onPortDragStart('outputs', idx)"
          @dragover="onPortDragOver($event, 'outputs', idx)"
          @drop="onPortDrop('outputs', idx)"
          @dragend="onPortDragEnd"
        >
          <span class="nde-port-drag i-carbon-draggable" />
          <span class="nde-port-index">{{ idx + 1 }}</span>
          <el-input
            v-model="port.name"
            size="small"
            placeholder="name"
            class="nde-port-name"
          />
          <el-select v-model="port.dataType" size="small" class="nde-port-type">
            <el-option v-for="t in PORT_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
          <!-- outputs have no default value -->
          <div class="nde-port-default" />
          <button class="nde-port-remove" @click="removeOutput(idx)">
            <span class="i-carbon-close" />
          </button>
        </div>

        <!-- Python code -->
        <div class="nde-section-title" style="margin-top:12px">Python Code</div>
        <div class="nde-signature">{{ generatedSignature }}</div>
        <textarea
          v-model="form.code"
          class="nde-code-area"
          spellcheck="false"
          :placeholder="`${generatedSignature}\n    # Your implementation here\n    return result`"
        />

      </div>

      <!-- ── Right column: preview ── -->
      <div class="nde-preview-col">
        <div class="nde-section-title">Preview</div>
        <div class="nde-preview-node">
          <!-- Control top (placeholder) -->
          <div class="nde-prev-ctrl-top">
            <div class="nde-prev-ctrl-dot" />
          </div>

          <!-- Node body -->
          <div class="nde-prev-body">
            <!-- Data input ports -->
            <div class="nde-prev-ports nde-prev-ports-left">
              <div
                v-for="port in previewInputs"
                :key="port.id"
                class="nde-prev-port nde-prev-port-in"
              >
                <div class="nde-prev-port-dot" style="background:#89b4fa" />
                <span class="nde-prev-port-label">{{ port.name || '?' }}</span>
                <span class="nde-prev-port-type">{{ port.dataType }}</span>
              </div>
              <div v-if="form.inputs.length > 5" class="nde-prev-more">
                +{{ form.inputs.length - 5 }} more
              </div>
            </div>

            <!-- Node name -->
            <div class="nde-prev-name">{{ form.name || 'My Node' }}</div>

            <!-- Data output ports -->
            <div class="nde-prev-ports nde-prev-ports-right">
              <div
                v-for="port in previewOutputs"
                :key="port.id"
                class="nde-prev-port nde-prev-port-out"
              >
                <span class="nde-prev-port-type">{{ port.dataType }}</span>
                <span class="nde-prev-port-label">{{ port.name || '?' }}</span>
                <div class="nde-prev-port-dot" style="background:#a6e3a1" />
              </div>
              <div v-if="form.outputs.length > 5" class="nde-prev-more">
                +{{ form.outputs.length - 5 }} more
              </div>
            </div>
          </div>

          <!-- Control bottom (placeholder) -->
          <div class="nde-prev-ctrl-bottom">
            <div class="nde-prev-ctrl-dot" />
          </div>
        </div>

        <!-- Type / category info -->
        <div class="nde-preview-meta">
          <div class="nde-preview-meta-row">
            <span class="nde-preview-meta-label">Type</span>
            <span class="nde-preview-meta-val">{{ derivedType }}</span>
          </div>
          <div class="nde-preview-meta-row">
            <span class="nde-preview-meta-label">Category</span>
            <span class="nde-preview-meta-val">{{ form.category }}</span>
          </div>
          <div class="nde-preview-meta-row">
            <span class="nde-preview-meta-label">Inputs</span>
            <span class="nde-preview-meta-val">{{ form.inputs.length }}</span>
          </div>
          <div class="nde-preview-meta-row">
            <span class="nde-preview-meta-label">Outputs</span>
            <span class="nde-preview-meta-val">{{ form.outputs.length }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Footer ── -->
    <template #footer>
      <div class="nde-footer">
        <el-button size="small" plain @click="handleCancel">Cancel</el-button>
        <el-button type="primary" size="small" @click="handleSave">
          <span class="i-carbon-save" style="margin-right:4px" />
          Save Node Type
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style>
/* ── Dialog body padding override (EP dark mode handles the rest) ── */
.node-def-dialog .el-dialog__body {
  padding: 0;
}

/* ── Root two-column layout ── */
.nde-root {
  display: flex;
  gap: 0;
  height: 580px;
  overflow: hidden;
}

/* ── Left: form ── */
.nde-form {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px 14px;
  border-right: 1px solid #313244;
}
.nde-form::-webkit-scrollbar {
  width: 4px;
}
.nde-form::-webkit-scrollbar-track {
  background: transparent;
}
.nde-form::-webkit-scrollbar-thumb {
  background: #313244;
  border-radius: 2px;
}

/* ── Section title ── */
.nde-section-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
  padding: 8px 0 4px;
  border-bottom: 1px solid #252535;
  margin-bottom: 8px;
}
.nde-section-title-with-btn {
  display: flex;
  align-items: center;
}

/* ── Field ── */
.nde-field {
  margin-bottom: 8px;
}
.nde-label {
  display: block;
  font-size: 11px;
  color: #6c7086;
  margin-bottom: 3px;
}
.nde-required {
  color: #f38ba8;
}
.nde-hint {
  font-size: 10px;
  color: #45475a;
  margin-top: 2px;
  display: block;
}

/* ── El-input dark overrides ── */
.nde-input :deep(.el-input__wrapper),
.nde-input :deep(.el-textarea__inner),
.nde-input :deep(.el-select__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 4px;
  color: #cdd6f4;
  font-size: 12px;
}
.nde-input :deep(.el-input__wrapper:hover),
.nde-input :deep(.el-input__wrapper.is-focus),
.nde-input :deep(.el-textarea__inner:focus),
.nde-input :deep(.el-select__wrapper:hover),
.nde-input :deep(.el-select__wrapper.is-focused) {
  border-color: #585b70;
  box-shadow: none;
}
.nde-input :deep(.el-input__inner),
.nde-input :deep(.el-textarea__inner) {
  color: #cdd6f4;
}
.nde-input :deep(.el-input__inner::placeholder),
.nde-input :deep(.el-textarea__inner::placeholder) {
  color: #45475a;
}
.nde-input :deep(.el-select__selected-item) {
  color: #cdd6f4;
}

/* ── Empty hint ── */
.nde-empty-hint {
  font-size: 11px;
  color: #45475a;
  font-style: italic;
  padding: 2px 0 6px;
}

/* ── Port add button ── */
.nde-port-add-btn {
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
.nde-port-add-btn:hover {
  background: rgba(137, 180, 250, 0.1);
  border-color: #89b4fa;
}

/* ── Port row ── */
.nde-port-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 0;
  cursor: row-resize;
}
.nde-port-drag {
  font-size: 14px;
  color: #45475a;
  cursor: grab;
  flex-shrink: 0;
}
.nde-port-index {
  flex-shrink: 0;
  width: 14px;
  text-align: right;
  font-size: 10px;
  color: #45475a;
}
.nde-port-name {
  flex: 1;
  min-width: 0;
}
.nde-port-type {
  width: 78px;
  flex-shrink: 0;
}
.nde-port-default {
  width: 70px;
  flex-shrink: 0;
}
.nde-port-remove {
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
.nde-port-remove:hover {
  color: #f38ba8;
  background: rgba(243, 139, 168, 0.1);
}

/* ── Port row el-input overrides ── */
.nde-port-name :deep(.el-input__wrapper),
.nde-port-default :deep(.el-input__wrapper),
.nde-port-type :deep(.el-select__wrapper) {
  background: #1e1e2e;
  box-shadow: none;
  border: 1px solid #313244;
  border-radius: 4px;
}
.nde-port-name :deep(.el-input__wrapper:hover),
.nde-port-name :deep(.el-input__wrapper.is-focus),
.nde-port-default :deep(.el-input__wrapper:hover),
.nde-port-default :deep(.el-input__wrapper.is-focus),
.nde-port-type :deep(.el-select__wrapper:hover),
.nde-port-type :deep(.el-select__wrapper.is-focused) {
  border-color: #585b70;
  box-shadow: none;
}
.nde-port-name :deep(.el-input__inner),
.nde-port-default :deep(.el-input__inner) {
  color: #cdd6f4;
  font-size: 11px;
}
.nde-port-name :deep(.el-input__inner::placeholder),
.nde-port-default :deep(.el-input__inner::placeholder) {
  color: #45475a;
}
.nde-port-type :deep(.el-select__selected-item) {
  color: #cdd6f4;
  font-size: 11px;
}

/* ── Signature ── */
.nde-signature {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  color: #89b4fa;
  background: #11111b;
  padding: 6px 8px;
  border-radius: 4px 4px 0 0;
  border: 1px solid #313244;
  border-bottom: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Code area ── */
.nde-code-area {
  display: block;
  width: 100%;
  box-sizing: border-box;
  min-height: 120px;
  background: #11111b;
  color: #cdd6f4;
  border: 1px solid #313244;
  border-radius: 0 0 4px 4px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.6;
  padding: 6px 8px;
  resize: vertical;
  outline: none;
  tab-size: 4;
  transition: border-color 0.1s;
}
.nde-code-area:focus {
  border-color: #585b70;
}
.nde-code-area::placeholder {
  color: #45475a;
}

/* ── Right column: preview ── */
.nde-preview-col {
  width: 200px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 12px 12px;
  gap: 0;
  overflow-y: auto;
}
.nde-preview-col::-webkit-scrollbar {
  width: 4px;
}
.nde-preview-col::-webkit-scrollbar-track {
  background: transparent;
}
.nde-preview-col::-webkit-scrollbar-thumb {
  background: #313244;
  border-radius: 2px;
}

/* ── Node preview widget ── */
.nde-preview-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 8px 0 12px;
}

.nde-prev-ctrl-top,
.nde-prev-ctrl-bottom {
  display: flex;
  justify-content: center;
  gap: 8px;
  padding: 4px 0;
}
.nde-prev-ctrl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fab387;
  border: 2px solid #181825;
}

.nde-prev-body {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  background: #1e1e2e;
  border: 1px solid #45475a;
  border-radius: 6px;
  min-width: 120px;
  max-width: 172px;
  padding: 6px 0;
  position: relative;
}

.nde-prev-ports {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 4px;
}
.nde-prev-ports-left {
  align-items: flex-start;
}
.nde-prev-ports-right {
  align-items: flex-end;
}

.nde-prev-port {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
}
.nde-prev-port-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid #181825;
}
.nde-prev-port-label {
  color: #a6adc8;
  white-space: nowrap;
  max-width: 44px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nde-prev-port-type {
  color: #45475a;
  font-size: 9px;
}
.nde-prev-more {
  font-size: 9px;
  color: #45475a;
  padding-left: 12px;
}

.nde-prev-name {
  flex: 1;
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  color: #cdd6f4;
  padding: 0 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  align-self: center;
}

/* ── Preview meta info ── */
.nde-preview-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  border-top: 1px solid #313244;
  padding-top: 10px;
}
.nde-preview-meta-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}
.nde-preview-meta-label {
  color: #6c7086;
}
.nde-preview-meta-val {
  color: #a6adc8;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Footer ── */
.nde-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}


</style>
