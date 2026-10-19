<template>
  <div class="robo-el" :class="[`robo-el--${g.shape}`, `kir-kind--${node.kind}`, { 'is-selected': selected }]" :style="{ width: `${g.w}px`, height: `${g.h}px` }" :title="tooltip">
    <svg class="robo-el__svg" :width="g.w" :height="g.h" :viewBox="`0 0 ${g.w} ${g.h}`">
      <path v-if="path" :d="path" class="robo-shape" />
      <template v-else-if="g.shape === 'defcall'">
        <rect x="0.75" y="0.75" :width="g.w - 1.5" :height="g.h - 1.5" rx="3" class="robo-shape" />
        <rect x="4" y="4" :width="g.w - 8" :height="g.h - 8" rx="2" class="robo-shape-inner" />
      </template>
      <rect v-else x="0.75" y="0.75" :width="g.w - 1.5" :height="g.h - 1.5" :rx="radius" class="robo-shape" />
      <line v-if="g.head && g.h > g.head + 4" x1="1" :x2="g.w - 1" :y1="g.head" :y2="g.head" class="robo-rule" />
      <text v-for="(t, i) in g.texts" :key="i" :x="t.x" :y="t.y" :text-anchor="t.anchor" :class="`robo-text robo-text--${t.cls}`">{{ t.text }}</text>
    </svg>
    <Handle v-for="p in g.ports" :id="p.handle" :key="p.handle" :type="p.dir === 'in' ? 'target' : 'source'" :position="POSITION[p.side]" :connectable="!p.fixed" class="robo-pin" :class="[`robo-pin--${p.flow}`, { 'robo-pin--free': p.free }]" :style="pinStyle(p)" :title="`${p.dir} ${p.name}${p.flow === 'data' ? ` (${p.type || '_'})` : ''}`" />
  </div>
</template>

<script setup>
import { computed } from "vue"
import { Handle, Position } from "@vue-flow/core"

import { shapePath } from "@/graph/styles/robo"

/** One flowchart element (ROBO Pro style); its geometry comes from graph/styles/robo.js. */
const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const POSITION = { top: Position.Top, bottom: Position.Bottom, left: Position.Left, right: Position.Right }
const PIN = 10

const node = computed(() => props.data.node)
const g = computed(() => props.data.geom)
const path = computed(() => shapePath(g.value))
const radius = computed(() => ({ value: 13, start: 15, end: 15, variable: 2, bar: 3 })[g.value.shape] ?? 3)

const tooltip = computed(() => {
  const n = node.value
  const hints = Object.entries(n.hints || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`)
  return [`${n.kind} · ${n.id}`, ...(hints.length ? [`@hint ${hints.join(" ")}`] : [])].join("\n")
})

function pinStyle(p) {
  return {
    left: `${p.x - PIN / 2}px`,
    top: `${p.y - PIN / 2}px`,
    right: "auto",
    bottom: "auto",
    transform: "none",
  }
}
</script>
