<template>
  <BaseEdge :id="id" :path="path" :marker-end="markerEnd" :interaction-width="14" :style="style" :class="['kir-edge', `kir-edge--${data.kind}`, { 'kir-edge--back': data.back }]" />
</template>

<script setup>
import { computed } from "vue"
import { BaseEdge, Position, getBezierPath } from "@vue-flow/core"

import { loopPoints, loopPointsLeft, roundedPath } from "@/graph/paths"

/**
 * A wire in any graph view: the ELK route while neither end has moved since
 * the layout, else a curve along the ports' sides; a control edge going back
 * against the flow loops around.
 */
const props = defineProps({
  id: { type: String, required: true },
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, default: Position.Bottom },
  targetPosition: { type: String, default: Position.Top },
  sourceNode: { type: Object, default: null },
  targetNode: { type: Object, default: null },
  data: { type: Object, required: true },
  markerEnd: { type: String, default: undefined },
})

const near = (a, b) => !!a && !!b && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5

const routeFits = computed(() => {
  const at = props.data.at
  if (!props.data.route || !at) return false
  return near(props.sourceNode?.computedPosition, at.s) && near(props.targetNode?.computedPosition, at.t)
})

const path = computed(() => {
  const s = { x: props.sourceX, y: props.sourceY }
  const t = { x: props.targetX, y: props.targetY }
  if (routeFits.value) return roundedPath([s, ...props.data.route, t])
  if (props.data.kind === "ctrl") {
    if (props.targetPosition === Position.Left && (props.data.back || t.x < s.x - 8))
      return roundedPath(loopPointsLeft(s.x, s.y, t.x, t.y), 10)
    if (props.targetPosition !== Position.Left && (props.data.back || t.y < s.y + 8))
      return roundedPath(loopPoints(s.x, s.y, t.x, t.y, props.targetPosition === Position.Right), 10)
  }
  const [d] = getBezierPath({
    sourceX: s.x,
    sourceY: s.y,
    sourcePosition: props.sourcePosition,
    targetX: t.x,
    targetY: t.y,
    targetPosition: props.targetPosition,
  })
  return d
})

const style = computed(() => ({
  stroke: props.data.color,
  strokeWidth: props.data.kind === "ctrl" ? 2.4 : 1.8,
}))
</script>
