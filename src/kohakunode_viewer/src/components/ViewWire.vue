<script setup>
import { computed } from 'vue'
import { dataWirePath, controlWirePath } from '../utils/bezier.js'

const props = defineProps({
  /**
   * Array of edge objects. Each edge has the shape produced by kirgraphToGraph:
   * {
   *   fromNodeId: string,
   *   fromPortId: string,
   *   toNodeId:   string,
   *   toPortId:   string,
   *   portType:   'data' | 'control',
   * }
   */
  edges: { type: Array, required: true },

  /**
   * Function (portId, nodeId, dir) => { x, y } | null
   *
   * Callers compute port positions from the ViewNode DOM data-attributes or
   * via the same math used in ViewNode (port index, node x/y/width/height).
   * This prop decouples wire rendering from DOM layout queries.
   *
   * dir: 'input' | 'output'
   */
  getPortPosition: { type: Function, required: true },

  /** Total canvas width (SVG width attribute) */
  canvasWidth: { type: Number, default: 4000 },

  /** Total canvas height (SVG height attribute) */
  canvasHeight: { type: Number, default: 4000 },
})

const wires = computed(() => {
  const result = []
  for (const edge of props.edges) {
    const from = props.getPortPosition(edge.fromPortId, edge.fromNodeId, 'output')
    const to   = props.getPortPosition(edge.toPortId,   edge.toNodeId,   'input')
    if (!from || !to) continue

    const d =
      edge.portType === 'control'
        ? controlWirePath(from.x, from.y, to.x, to.y)
        : dataWirePath(from.x, from.y, to.x, to.y)

    result.push({
      key:      `${edge.fromNodeId}:${edge.fromPortId}-->${edge.toNodeId}:${edge.toPortId}`,
      d,
      portType: edge.portType,
    })
  }
  return result
})
</script>

<template>
  <!--
    Single SVG layer covering the full canvas.
    overflow: visible so bezier handles that extend outside the bounding box
    are still drawn.
    pointer-events: none — all clicks pass through to nodes beneath.
  -->
  <svg
    class="view-wire-layer"
    xmlns="http://www.w3.org/2000/svg"
    :width="canvasWidth"
    :height="canvasHeight"
    overflow="visible"
  >
    <g class="wires">
      <path
        v-for="wire in wires"
        :key="wire.key"
        :d="wire.d"
        :class="['wire', wire.portType === 'control' ? 'wire-control' : 'wire-data']"
        fill="none"
      />
    </g>
  </svg>
</template>

<style scoped>
.view-wire-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}

/* Data wires — blue, 2px */
.wire-data {
  stroke: #89b4fa;
  stroke-width: 2;
  stroke-linecap: round;
  opacity: 0.85;
}

/* Control wires — orange, 3px */
.wire-control {
  stroke: #fab387;
  stroke-width: 3;
  stroke-linecap: round;
  opacity: 0.85;
}
</style>
