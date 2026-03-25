<script setup>
import { computed } from "vue";

const props = defineProps({
  /**
   * { x1, y1, x2, y2 } — screen coordinates, any corner ordering.
   */
  box: {
    type: Object,
    required: true,
  },
});

const style = computed(() => {
  const x = Math.min(props.box.x1, props.box.x2);
  const y = Math.min(props.box.y1, props.box.y2);
  const w = Math.abs(props.box.x2 - props.box.x1);
  const h = Math.abs(props.box.y2 - props.box.y1);
  return {
    left: `${x}px`,
    top: `${y}px`,
    width: `${w}px`,
    height: `${h}px`,
  };
});
</script>

<template>
  <div class="selection-box" :style="style" />
</template>

<style scoped>
.selection-box {
  position: absolute;
  pointer-events: none;
  z-index: 100;
  border: 1px solid #89b4fa;
  background: rgba(137, 180, 250, 0.08);
  border-radius: 2px;
  box-shadow: 0 0 0 1px rgba(137, 180, 250, 0.2);
}
</style>
