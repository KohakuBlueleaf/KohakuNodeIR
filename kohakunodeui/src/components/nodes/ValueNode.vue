<script setup>
import { ref, watch } from 'vue'

const props = defineProps({ node: { type: Object, required: true } })
const emit = defineEmits(['update:property'])

const VALUE_TYPES = ['int', 'float', 'string', 'bool', 'none']
const localType = ref(props.node.properties?.valueType ?? 'string')
const localValue = ref(props.node.properties?.value ?? '')

watch(() => props.node.properties?.valueType, v => { if (v !== undefined) localType.value = v })
watch(() => props.node.properties?.value, v => { if (v !== undefined) localValue.value = v })

function onTypeChange(e) {
  const t = e.target.value
  localType.value = t
  emit('update:property', { key: 'valueType', value: t })
  let def = ''
  if (t === 'int') def = 0
  if (t === 'float') def = 0.0
  if (t === 'bool') def = false
  if (t === 'none') def = null
  localValue.value = def
  emit('update:property', { key: 'value', value: def })
}

function onValueChange(e) {
  let v = e.target.value
  if (localType.value === 'int') v = parseInt(v, 10)
  if (localType.value === 'float') v = parseFloat(v)
  localValue.value = v
  emit('update:property', { key: 'value', value: v })
}

function onBoolChange(e) {
  localValue.value = e.target.checked
  emit('update:property', { key: 'value', value: e.target.checked })
}
</script>

<template>
  <div class="value-body">
    <div class="type-row">
      <label class="lbl">type</label>
      <select class="sel" :value="localType" @change="onTypeChange" @pointerdown.stop @click.stop>
        <option v-for="t in VALUE_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
    </div>
    <div class="val-row">
      <span v-if="localType === 'none'" class="none-ph">null</span>
      <label v-else-if="localType === 'bool'" class="bool-lbl">
        <input type="checkbox" :checked="!!localValue" @change="onBoolChange" @pointerdown.stop @click.stop />
        {{ localValue ? 'true' : 'false' }}
      </label>
      <input v-else class="val-input" :type="localType === 'int' || localType === 'float' ? 'number' : 'text'"
        :value="localValue" placeholder="0" @change="onValueChange" @pointerdown.stop @click.stop />
    </div>
  </div>
</template>

<style scoped>
.value-body { display: flex; flex-direction: column; gap: 4px; font-size: 11px; }
.type-row { display: flex; align-items: center; gap: 6px; }
.lbl { font-size: 9px; font-weight: 700; text-transform: uppercase; color: #6c7086; }
.sel { flex: 1; background: #11111b; border: 1px solid #45475a; border-radius: 3px; color: #cdd6f4; font-size: 10px; padding: 2px 4px; outline: none; }
.sel:focus { border-color: #89b4fa; }
.val-row { display: flex; align-items: center; }
.val-input { width: 100%; padding: 3px 6px; border-radius: 3px; border: 1px solid #45475a; background: #11111b; color: #cdd6f4; font-size: 11px; font-family: monospace; outline: none; }
.val-input:focus { border-color: #89b4fa; }
.none-ph { color: #6c7086; font-style: italic; font-family: monospace; padding: 3px 6px; border: 1px solid #313244; border-radius: 3px; background: #11111b; width: 100%; }
.bool-lbl { display: flex; align-items: center; gap: 6px; cursor: pointer; font-family: monospace; color: #fab387; }
</style>
