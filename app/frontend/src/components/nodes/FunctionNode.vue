<script setup>
const props = defineProps({ node: { type: Object, required: true } })
const emit = defineEmits(['update:property'])
</script>

<template>
  <div class="fn-body">
    <div v-if="node.properties?.code" class="code-badge">has code</div>
  </div>
</template>

<style scoped>
.fn-body { font-size: 11px; }
.code-badge { display: inline-flex; align-items: center; gap: 4px; padding: 1px 6px; border-radius: 3px; background: rgba(137,180,250,0.12); border: 1px solid rgba(137,180,250,0.25); color: #89b4fa; font-size: 10px; font-weight: 600; width: fit-content; }
</style>
