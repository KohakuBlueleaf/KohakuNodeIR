<template>
  <g class="kg-wire" :data-ends="`${data.source}|${data.sourceHandle}|${data.target}|${data.targetHandle}`" :data-keys="data.keys.join(' ')" :class="[`kg-wire--${data.kind}`, { 'kg-wire--back': data.back, 'is-active': entry?.active, 'is-selected': selected }]">
    <path :d="d" class="kg-wire__hit" />
    <path :d="d" class="kg-wire__line" :style="{ stroke: data.color, strokeWidth: width }" :marker-end="data.arrow ? `url(#${markerId})` : undefined" />
    <path v-if="rail" :d="d" class="kg-wire__core" :style="{ strokeWidth: width * 0.4 }" />
    <text v-if="tail" :x="tail.x" :y="tail.y" :text-anchor="tail.anchor" class="kg-wire__tail" :style="{ fill: data.color }">{{ data.tail }}</text>
    <text v-if="entry?.label && mid" :x="mid.x" :y="mid.y - 4" class="kg-wire__label">{{ entry.label }}</text>
  </g>
</template>

<script setup>
import { computed } from "vue"

import { orthoRoute } from "../../layout/route.js"
import { useGraphState } from "../overlay.js"
import { midpoint, roundedPath } from "./paths.js"

/**
 * A wire along its routed path (layout/build.js); every drawn edge has one. In
 * the "rail" wire style control is a hollow double line and data a thin single
 * one, so the two read apart by shape, not by colour alone; "plain" draws both
 * as solid lines of their colour. Its overlay entry widens it by weight,
 * labels it, or marks it active; a wire leaving a branching element carries
 * the arm's name (`tail`) where it leaves. While an end's element is dragged
 * away from where the route was made (`sourceAt`, `targetAt`), the wire
 * follows it on an orthogonal route (layout/route.js).
 */
const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  sourceNode: { type: Object, default: null },
  targetNode: { type: Object, default: null },
})

const state = useGraphState()

const shift = (node, at) => {
  const p = node?.position
  if (!p || !at) return null
  const d = { x: p.x - at.x, y: p.y - at.y }
  return Math.abs(d.x) > 0.5 || Math.abs(d.y) > 0.5 ? d : null
}
const route = computed(() => {
  const r = props.data.route
  if (!r || !state.editable?.value) return r
  const ds = shift(props.sourceNode, props.data.sourceAt)
  const dt = shift(props.targetNode, props.data.targetAt)
  if (!ds && !dt) return r
  const a = { x: r[0].x + (ds?.x ?? 0), y: r[0].y + (ds?.y ?? 0) }
  const b = { x: r[r.length - 1].x + (dt?.x ?? 0), y: r[r.length - 1].y + (dt?.y ?? 0) }
  const box = (node, size) => ({ x: node.position.x, y: node.position.y, ...size })
  return orthoRoute(a, props.data.sourceSide, b, props.data.targetSide, [box(props.sourceNode, props.data.sourceSize), box(props.targetNode, props.data.targetSize)])
})
const entry = computed(() => {
  for (const k of props.data.keys) {
    const e = state.edges.get(k)
    if (e) return e
  }
  return null
})
const ctrl = computed(() => props.data.kind === "ctrl")
const rail = computed(() => ctrl.value && state.wireStyle?.value !== "plain")
const d = computed(() => (route.value ? roundedPath(route.value, ctrl.value ? 5 : 10) : ""))
const mid = computed(() => (route.value ? midpoint(route.value) : null))
const base = computed(() => {
  if (state.wireStyle?.value === "plain") return ctrl.value ? 2.2 : 1.6
  return ctrl.value ? 4.4 : 1.3
})
const width = computed(() => (entry.value?.weight != null ? base.value + 4 * Math.max(0, Math.min(1, entry.value.weight)) : base.value))
const markerId = computed(() => `kg-arrow-${props.data.kind}${props.data.palette === "robo" ? "-robo" : ""}`)

// The arm's name beside the first stretch of the wire, clear of the element it leaves
const tail = computed(() => {
  const r = route.value
  if (!props.data.tail || !r || r.length < 2) return null
  const [a, b] = r
  if (Math.abs(b.x - a.x) > Math.abs(b.y - a.y)) return { x: a.x + Math.sign(b.x - a.x) * 8, y: a.y - 7, anchor: b.x > a.x ? "start" : "end" }
  return { x: a.x + 10, y: a.y + Math.sign(b.y - a.y) * 15 + 3, anchor: "start" }
})
</script>
