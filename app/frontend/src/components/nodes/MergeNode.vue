<script setup>
defineProps({ node: { type: Object, required: true } })
const emit = defineEmits(['add-control-input'])
</script>

<template>
  <div class="merge-body">
    <button class="add-btn" @click.stop="emit('add-control-input')" @pointerdown.stop>
      <span>+</span> add input
    </button>
  </div>
</template>

<style scoped>
.merge-body { font-size: 11px; display: flex; flex-direction: column; gap: 4px; }
.add-btn { display: flex; align-items: center; gap: 4px; padding: 2px 6px; border-radius: 4px; border: 1px dashed #45475a; background: transparent; color: #6c7086; font-size: 10px; cursor: pointer; width: 100%; justify-content: center; transition: border-color 0.12s, color 0.12s; }
.add-btn:hover { border-color: #fab387; color: #fab387; }
</style>
