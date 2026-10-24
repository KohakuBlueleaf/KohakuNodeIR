<template>
  <g class="kg-wire" :data-ends="`${data.source}|${data.sourceHandle}|${data.target}|${data.targetHandle}`" :class="[`kg-wire--${data.kind}`, { 'kg-wire--back': data.back, 'is-active': entry?.active, 'is-selected': selected }]">
    <path :d="d" class="kg-wire__hit" />
    <path :d="d" class="kg-wire__line" :style="{ stroke: data.color, strokeWidth: width }" :marker-end="data.arrow ? `url(#${markerId})` : undefined" />
    <path v-if="rail" :d="d" class="kg-wire__core" :style="{ strokeWidth: width * 0.4 }" />
    <text v-if="tail" :x="tail.x" :y="tail.y" :text-anchor="tail.anchor" class="kg-wire__tail" :style="{ fill: data.color }">{{ data.tail }}</text>
    <text v-if="entry?.label && mid" :x="mid.x" :y="mid.y - 4" class="kg-wire__label">{{ entry.label }}</text>
  </g>
</template>

<script setup>
import { computed } from "vue"

import { useGraphState } from "../overlay.js"
import { midpoint, roundedPath } from "./paths.js"

/**
 * A wire along its routed path (layout/build.js); every drawn edge has one. In
 * the "rail" wire style control is a hollow double line and data a thin single
 * one, so the two read apart by shape, not by colour alone; "plain" draws both
 * as solid lines of their colour. Its overlay entry widens it by weight,
 * labels it, or marks it active; a wire leaving a branching element carries
 * the arm's name (`tail`) where it leaves.
 */
const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const state = useGraphState()
const entry = computed(() => {
  for (const k of props.data.keys) {
    const e = state.edges.get(k)
    if (e) return e
  }
  return null
})
const ctrl = computed(() => props.data.kind === "ctrl")
const rail = computed(() => ctrl.value && state.wireStyle?.value !== "plain")
const d = computed(() => (props.data.route ? roundedPath(props.data.route, ctrl.value ? 5 : 10) : ""))
const mid = computed(() => (props.data.route ? midpoint(props.data.route) : null))
const base = computed(() => {
  if (state.wireStyle?.value === "plain") return ctrl.value ? 2.2 : 1.6
  return ctrl.value ? 4.4 : 1.3
})
const width = computed(() => (entry.value?.weight != null ? base.value + 4 * Math.max(0, Math.min(1, entry.value.weight)) : base.value))
const markerId = computed(() => `kg-arrow-${props.data.kind}${props.data.palette === "robo" ? "-robo" : ""}`)

// The arm's name beside the first stretch of the wire, clear of the element it leaves
const tail = computed(() => {
  const r = props.data.route
  if (!props.data.tail || !r || r.length < 2) return null
  const [a, b] = r
  if (Math.abs(b.x - a.x) > Math.abs(b.y - a.y)) return { x: a.x + Math.sign(b.x - a.x) * 8, y: a.y - 7, anchor: b.x > a.x ? "start" : "end" }
  return { x: a.x + 10, y: a.y + Math.sign(b.y - a.y) * 15 + 3, anchor: "start" }
})
</script>
