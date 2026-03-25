<script setup>
import { computed } from "vue";
import { useGraphStore } from "../../stores/graph.js";
import { useEditorStore } from "../../stores/editor.js";
import { dataWirePath, controlWirePath } from "../../utils/bezier.js";

const graph = useGraphStore();
const editor = useEditorStore();

/**
 * Build a list of renderable wire descriptors from the connection list.
 * Each entry: { id, d, portType, selected }
 */
const wires = computed(() => {
  const result = [];
  for (const conn of graph.connectionList) {
    const from = graph.getPortPosition(conn.fromNodeId, conn.fromPortId);
    const to = graph.getPortPosition(conn.toNodeId, conn.toPortId);
    if (!from || !to) continue;

    const d =
      conn.portType === "control"
        ? controlWirePath(from.x, from.y, to.x, to.y)
        : dataWirePath(from.x, from.y, to.x, to.y);

    result.push({
      id: conn.id,
      d,
      portType: conn.portType,
      selected: editor.selectedConnectionIds.has(conn.id),
    });
  }
  return result;
});

function onWireClick(e, wireId) {
  e.stopPropagation();
  editor.selectConnection(wireId, e.ctrlKey || e.metaKey || e.shiftKey);
}
</script>

<template>
  <!--
    The SVG fills the full canvas-transform div.
    overflow: visible so bezier handles that drift outside the bounding box are still drawn.
    pointer-events: none on the layer itself; individual hit-area paths enable clicks.
  -->
  <svg class="wire-layer" xmlns="http://www.w3.org/2000/svg" overflow="visible">
    <g class="wires">
      <g v-for="wire in wires" :key="wire.id">
        <!-- Invisible wide hit-area path for easy clicking -->
        <path
          :d="wire.d"
          class="wire-hit"
          fill="none"
          @click="onWireClick($event, wire.id)"
        />
        <!-- Visible wire path -->
        <path
          :d="wire.d"
          :class="[
            'wire',
            wire.portType === 'control' ? 'wire-control' : 'wire-data',
            wire.selected ? 'wire--selected' : '',
          ]"
          fill="none"
          style="pointer-events: none"
        />
      </g>
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

/* Wide invisible hit area — receives pointer events */
.wire-hit {
  stroke: transparent;
  stroke-width: 12;
  cursor: pointer;
  pointer-events: stroke;
}

/* Data wires — blue, thinner */
.wire-data {
  stroke: #89b4fa;
  stroke-width: 2;
  stroke-linecap: round;
  opacity: 0.85;
  transition:
    stroke 0.1s,
    opacity 0.1s,
    stroke-width 0.1s;
}

/* Control wires — orange, thicker */
.wire-control {
  stroke: #fab387;
  stroke-width: 3;
  stroke-linecap: round;
  opacity: 0.85;
  transition:
    stroke 0.1s,
    opacity 0.1s,
    stroke-width 0.1s;
}

/* Selected state — highlight colour and glow */
.wire--selected.wire-data {
  stroke: #b4d0ff;
  stroke-width: 3;
  opacity: 1;
  filter: drop-shadow(0 0 4px rgba(137, 180, 250, 0.8));
}

.wire--selected.wire-control {
  stroke: #ffcba0;
  stroke-width: 4;
  opacity: 1;
  filter: drop-shadow(0 0 4px rgba(250, 179, 135, 0.8));
}
</style>
