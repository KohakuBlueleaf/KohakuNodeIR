<script setup>
/**
 * ValueNode — body content for 'value' type nodes.
 * Rendered inside BaseNode's #body slot via NodeRenderer.
 *
 * Layout:
 *   - Compact inline type selector (int / float / string / bool / none)
 *   - Editable literal value field that adapts to the chosen type
 *   - Single data output indicator
 *
 * No control ports, no data inputs.
 *
 * Emits:
 *   - update:property  { key: 'valueType' | 'value', value: any }
 */

import { ref, computed, watch } from 'vue';

const props = defineProps({
  node: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(['update:property']);

// ---- Local state (mirrors properties, allows immediate reactivity) ----

const VALUE_TYPES = ['int', 'float', 'string', 'bool', 'none'];

const localType  = ref(props.node.properties?.valueType  ?? 'string');
const localValue = ref(props.node.properties?.value      ?? '');

// Keep in sync if the node prop changes externally
watch(() => props.node.properties?.valueType, v => { if (v !== undefined) localType.value = v; });
watch(() => props.node.properties?.value,     v => { if (v !== undefined) localValue.value = v; });

// ---- Derived ----

/** The type-appropriate display for the input widget. */
const inputType = computed(() => {
  switch (localType.value) {
    case 'int':
    case 'float': return 'number';
    default:      return 'text';
  }
});

const isBool = computed(() => localType.value === 'bool');
const isNone = computed(() => localType.value === 'none');

// ---- Handlers ----

function onTypeChange(event) {
  const newType = event.target.value;
  localType.value = newType;
  emit('update:property', { key: 'valueType', value: newType });

  // Reset value to a sane default for the chosen type
  let defaultVal = '';
  if (newType === 'int')    defaultVal = 0;
  if (newType === 'float')  defaultVal = 0.0;
  if (newType === 'bool')   defaultVal = false;
  if (newType === 'none')   defaultVal = null;
  localValue.value = defaultVal;
  emit('update:property', { key: 'value', value: defaultVal });
}

function onValueChange(event) {
  let raw = event.target.value;
  let coerced = raw;
  if (localType.value === 'int')   coerced = parseInt(raw, 10);
  if (localType.value === 'float') coerced = parseFloat(raw);
  localValue.value = coerced;
  emit('update:property', { key: 'value', value: coerced });
}

function onBoolChange(event) {
  const val = event.target.checked;
  localValue.value = val;
  emit('update:property', { key: 'value', value: val });
}
</script>

<template>
  <div class="value-body">

    <!-- Type selector -->
    <div class="type-row">
      <label class="type-label-text">type</label>
      <select
        class="type-select"
        :value="localType"
        @change="onTypeChange"
        @pointerdown.stop
        @click.stop
      >
        <option v-for="t in VALUE_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
    </div>

    <!-- Value editor -->
    <div class="value-row">
      <!-- None: just a muted placeholder -->
      <span v-if="isNone" class="none-placeholder">null</span>

      <!-- Bool: checkbox -->
      <label v-else-if="isBool" class="bool-label">
        <input
          type="checkbox"
          class="bool-check"
          :checked="!!localValue"
          @change="onBoolChange"
          @pointerdown.stop
          @click.stop
        />
        <span class="bool-text">{{ localValue ? 'true' : 'false' }}</span>
      </label>

      <!-- Number / string -->
      <input
        v-else
        class="value-input"
        :type="inputType"
        :value="localValue"
        :placeholder="localType === 'string' ? '\"value\"' : '0'"
        @change="onValueChange"
        @pointerdown.stop
        @click.stop
      />
    </div>

    <!-- Output port indicator -->
    <div class="output-row">
      <span class="out-label">value</span>
      <span class="port-dot" />
    </div>

  </div>
</template>

<style scoped>
.value-body {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11px;
}

/* Type row */
.type-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.type-label-text {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
  flex-shrink: 0;
}

.type-select {
  flex: 1;
  background: #11111b;
  border: 1px solid #45475a;
  border-radius: 3px;
  color: #cdd6f4;
  font-size: 10px;
  padding: 2px 4px;
  outline: none;
  cursor: pointer;
}
.type-select:focus {
  border-color: #89b4fa;
}

/* Value row */
.value-row {
  display: flex;
  align-items: center;
}

.value-input {
  width: 100%;
  padding: 3px 6px;
  border-radius: 3px;
  border: 1px solid #45475a;
  background: #11111b;
  color: #cdd6f4;
  font-size: 11px;
  font-family: monospace;
  outline: none;
  box-sizing: border-box;
}
.value-input:focus {
  border-color: #89b4fa;
}
.value-input[type="number"] {
  color: #89dceb;
}

.none-placeholder {
  color: #6c7086;
  font-style: italic;
  font-size: 11px;
  font-family: monospace;
  padding: 3px 6px;
  border: 1px solid #313244;
  border-radius: 3px;
  background: #11111b;
  width: 100%;
}

.bool-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.bool-check {
  accent-color: #89b4fa;
  width: 13px;
  height: 13px;
  cursor: pointer;
}
.bool-text {
  font-family: monospace;
  color: #fab387;
  font-size: 11px;
}

/* Output indicator */
.output-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  padding-top: 4px;
  border-top: 1px solid #313244;
  margin-top: 2px;
}

.out-label {
  font-size: 10px;
  color: #9399b2;
}

.port-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #89b4fa; /* data output */
  flex-shrink: 0;
}
</style>
