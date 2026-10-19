<template>
  <div class="kir-node group" :class="[`kir-node--${g.shape}`, `kir-kind--${node.kind}`, { 'is-selected': selected }]" :style="{ width: `${g.w}px`, height: `${g.h}px` }" :title="tooltip">
    <svg class="kir-node__svg" :width="g.w" :height="g.h" :viewBox="`0 0 ${g.w} ${g.h}`">
      <path v-if="path" :d="path" class="kir-shape" />
      <template v-else-if="g.shape === 'defcall'">
        <rect x="0.75" y="0.75" :width="g.w - 1.5" :height="g.h - 1.5" rx="10" class="kir-shape" />
        <rect x="4" y="4" :width="g.w - 8" :height="g.h - 8" rx="7" class="kir-shape-inner" />
      </template>
      <rect v-else x="0.75" y="0.75" :width="g.w - 1.5" :height="g.h - 1.5" :rx="radius" class="kir-shape" />
      <line v-if="g.head && g.h > g.head + 4" x1="1" :x2="g.w - 1" :y1="g.head" :y2="g.head" class="kir-head-rule" />
      <text v-for="(t, i) in g.texts" :key="i" :x="t.x" :y="t.y" :text-anchor="t.anchor" :class="`kir-text kir-text--${t.cls}`">{{ t.text }}</text>
      <circle v-if="hasHints" :cx="g.w - 9" cy="9" r="3" class="kir-hint-dot" />
    </svg>
    <Handle v-for="p in g.ports" :id="p.handle" :key="p.handle" :type="p.dir === 'in' ? 'target' : 'source'" :position="POSITION[p.side]" :connectable="true" class="kir-port" :class="[`kir-port--${p.flow}`, { 'kir-port--free': p.free }]" :style="portStyle(p)" :title="portTitle(p)" />
  </div>
</template>

<script setup>
import { computed } from "vue"
import { Handle, Position } from "@vue-flow/core"

import { shapePath } from "@/graph/geometry"

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const POSITION = { top: Position.Top, bottom: Position.Bottom, left: Position.Left, right: Position.Right }
const PORT = 10

const node = computed(() => props.data.node)
const g = computed(() => props.data.geom)
const path = computed(() => shapePath(g.value))
const radius = computed(() => ({ value: 14, get: 14, bar: 5 })[g.value.shape] ?? 8)
const hasHints = computed(() => Object.keys(node.value.hints || {}).length > 0)

const tooltip = computed(() => {
  const n = node.value
  const parts = [`${n.kind} · ${n.id}`]
  if (hasHints.value) parts.push(`@hint ${Object.entries(n.hints).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" ")}`)
  return parts.join("\n")
})

function portStyle(p) {
  return {
    left: `${p.x - PORT / 2}px`,
    top: `${p.y - PORT / 2}px`,
    right: "auto",
    bottom: "auto",
    transform: "none",
    "--port-color": p.color,
  }
}

function portTitle(p) {
  const what = p.flow === "ctrl" ? "control" : p.type || "_"
  return `${p.dir === "in" ? "in" : "out"} ${p.name} (${what})`
}
</script>
