<script setup>
import { computed } from 'vue';
import { dataWirePath, controlWirePath } from '../../utils/bezier.js';

const props = defineProps({
  /**
   * {
   *   fromX: number,   — screen x of the port the drag started on
   *   fromY: number,
   *   toX:   number,   — current mouse screen x
   *   toY:   number,
   *   portType: 'data' | 'control'
   * }
   */
  wire: {
    type: Object,
    required: true,
  },
});

const pathD = computed(() => {
  const { fromX, fromY, toX, toY, portType } = props.wire;
  return portType === 'control'
    ? controlWirePath(fromX, fromY, toX, toY)
    : dataWirePath(fromX, fromY, toX, toY);
});

const strokeColor = computed(() =>
  props.wire.portType === 'control' ? '#fab387' : '#89b4fa'
);

const strokeWidth = computed(() =>
  props.wire.portType === 'control' ? 3 : 2
);
</script>

<template>
  <!--
    Positioned as a full-screen SVG overlay (screen coordinates, outside the
    pan/zoom transform) so the path is always drawn in the right place while
    the user is dragging.
  -->
  <svg
    class="draft-wire-overlay"
    xmlns="http://www.w3.org/2000/svg"
    overflow="visible"
  >
    <path
      :d="pathD"
      :stroke="strokeColor"
      :stroke-width="strokeWidth"
      stroke-dasharray="8 5"
      stroke-linecap="round"
      fill="none"
      opacity="0.7"
    />
    <!-- Endpoint dot at the dragging end -->
    <circle
      :cx="wire.toX"
      :cy="wire.toY"
      r="4"
      :fill="strokeColor"
      opacity="0.6"
    />
  </svg>
</template>

<style scoped>
.draft-wire-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 50;
}
</style>
