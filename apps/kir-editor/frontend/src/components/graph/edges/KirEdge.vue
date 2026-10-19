<template>
  <BaseEdge :id="id" :path="path" :marker-end="markerEnd" :interaction-width="14" :style="style" :class="['kir-edge', `kir-edge--${data.kind}`, { 'kir-edge--back': data.back, 'is-selected': selected }]" />
</template>

<script setup>
import { computed } from "vue"
import { BaseEdge, Position, getBezierPath } from "@vue-flow/core"

import { loopPoints, roundedPath } from "@/graph/paths"

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
  selected: { type: Boolean, default: false },
})

const near = (a, b) => !!a && !!b && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5

/** The ELK route still fits while neither end has moved since the layout. */
const routeFits = computed(() => {
  const at = props.data.at
  if (!props.data.route || !at) return false
  return near(props.sourceNode?.computedPosition, at.s) && near(props.targetNode?.computedPosition, at.t)
})

const path = computed(() => {
  const s = { x: props.sourceX, y: props.sourceY }
  const t = { x: props.targetX, y: props.targetY }
  if (routeFits.value) return roundedPath([s, ...props.data.route, t])
  const upward = props.data.kind === "ctrl" && (props.data.back || t.y < s.y + 8)
  if (upward) return roundedPath(loopPoints(s.x, s.y, t.x, t.y, props.targetPosition === Position.Right), 10)
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
  strokeWidth: props.data.kind === "ctrl" ? 2 : 1.6,
}))
</script>
