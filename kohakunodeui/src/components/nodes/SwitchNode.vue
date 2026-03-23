<script setup>
import { computed } from 'vue'

const props = defineProps({ node: { type: Object, required: true } })
const emit = defineEmits(['add-case', 'remove-case'])

const caseOutputs = computed(() => props.node.controlPorts?.outputs ?? [])
</script>

<template>
  <div class="switch-body">
    <div class="cases-list">
      <div v-for="port in caseOutputs" :key="port.id" class="case-row">
        <span class="case-label">{{ port.name }}</span>
        <button class="rm" @click.stop="emit('remove-case', { portId: port.id })" @pointerdown.stop>x</button>
      </div>
    </div>
    <button class="add-btn" @click.stop="emit('add-case')" @pointerdown.stop>
      <span>+</span> add case
    </button>
  </div>
</template>

<style scoped>
.switch-body { display: flex; flex-direction: column; gap: 4px; font-size: 11px; }
.cases-list { display: flex; flex-direction: column; gap: 2px; }
.case-row { display: flex; align-items: center; gap: 4px; }
.case-label { flex: 1; color: #bac2de; font-size: 10px; font-family: monospace; }
.rm { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #45475a; background: transparent; color: #6c7086; font-size: 11px; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0; }
.rm:hover { border-color: #f38ba8; color: #f38ba8; }
.add-btn { display: flex; align-items: center; gap: 4px; padding: 2px 6px; border-radius: 4px; border: 1px dashed #45475a; background: transparent; color: #6c7086; font-size: 10px; cursor: pointer; width: 100%; justify-content: center; }
.add-btn:hover { border-color: #cba6f7; color: #cba6f7; }
</style>
