<script setup>
import { computed } from 'vue';
import { useGraphStore } from '../../stores/graph.js';
import { dataWirePath, controlWirePath } from '../../utils/bezier.js';

const graph = useGraphStore();

/**
 * Build a list of renderable wire descriptors from the connection list.
 * Each entry: { id, d, portType }
 */
const wires = computed(() => {
  const result = [];
  for (const conn of graph.connectionList) {
    const from = graph.getPortPosition(conn.fromNodeId, conn.fromPortId);
    const to   = graph.getPortPosition(conn.toNodeId,   conn.toPortId);
    if (!from || !to) continue;

    const d =
      conn.portType === 'control'
        ? controlWirePath(from.x, from.y, to.x, to.y)
        : dataWirePath(from.x, from.y, to.x, to.y);

    result.push({ id: conn.id, d, portType: conn.portType });
  }
  return result;
});
</script>

<template>
  <!--
    The SVG fills the full canvas-transform div.
    overflow: visible so bezier handles that drift outside the bounding box are still drawn.
    pointer-events: none — clicks pass through to nodes below.
  -->
  <svg
    class="wire-layer"
    xmlns="http://www.w3.org/2000/svg"
    overflow="visible"
  >
    <g class="wires">
      <path
        v-for="wire in wires"
        :key="wire.id"
        :d="wire.d"
        :class="['wire', wire.portType === 'control' ? 'wire-control' : 'wire-data']"
        fill="none"
      />
    </g>
  </svg>
</template>

<style scoped>
.wire-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}

/* Data wires — blue, thinner */
.wire-data {
  stroke: #89b4fa;
  stroke-width: 2;
  stroke-linecap: round;
  opacity: 0.85;
}

/* Control wires — orange, thicker */
.wire-control {
  stroke: #fab387;
  stroke-width: 3;
  stroke-linecap: round;
  opacity: 0.85;
}
</style>
