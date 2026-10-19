<template>
  <!-- Variable / literal pill -->
  <div v-if="g.shape === 'pill'" class="kir-pill" :class="[`kir-pill--${g.variant}`, { 'is-selected': selected }]" :style="{ width: `${g.w}px`, height: `${g.h}px` }" :title="`${node.kind} · ${node.id}`">
    <span v-if="g.variant === 'get'" class="i-carbon-download kir-pill__icon" />
    <span v-else-if="g.variant === 'set'" class="i-carbon-upload kir-pill__icon" />
    <LiteralWidget v-if="g.variant === 'value'" class="kir-pill__widget" :value="node.props?.value" @commit="(v) => commit('value', v)" />
    <span v-else class="kir-pill__name">{{ g.title }}</span>
    <Handle v-for="p in g.ports" :id="p.handle" :key="p.handle" :type="p.dir === 'in' ? 'target' : 'source'" :position="p.side === 'left' ? Position.Left : Position.Right" class="kir-pin kir-pin--data" :style="pinStyle(p)" :title="p.name" />
  </div>

  <!-- Card -->
  <div v-else class="kir-card" :class="[`kir-card--${g.variant}`, `kir-accent--${g.accent}`, { 'is-selected': selected }]" :style="{ width: `${g.w}px`, height: `${g.h}px` }" :title="`${node.kind} · ${node.id}${hints ? `\n@hint ${hints}` : ''}`">
    <div class="kir-card__head" :style="{ height: `${HEAD}px` }">
      <span :class="ICON[g.variant] || ICON[node.kind] || 'i-carbon-function'" class="kir-card__icon" />
      <span class="kir-card__title">{{ g.title }}</span>
      <span v-if="hints" class="kir-card__hint" title="has @hint" />
    </div>
    <div v-for="(row, i) in g.rows" :key="i" class="kir-card__row" :style="{ top: `${row.y - ROW / 2}px`, height: `${ROW}px` }">
      <div v-if="row.left" class="kir-card__cell kir-card__cell--left">
        <span class="kir-card__label" :class="{ 'is-ctrl': row.left.flow === 'ctrl' }">{{ row.left.label }}</span>
        <LiteralWidget v-if="row.left.flow === 'data' && !isWired(row.left.name)" class="kir-card__widget" :value="row.left.input?.value" :type="row.left.type" :placeholder="row.left.type || 'value'" @commit="(v) => commit(row.left.name, v)" />
        <span v-else-if="row.left.flow === 'data'" class="kir-card__wired">wired</span>
      </div>
      <div v-if="row.right" class="kir-card__cell kir-card__cell--right">
        <span class="kir-card__label" :class="{ 'is-ctrl': row.right.flow === 'ctrl' }">{{ row.right.label }}</span>
      </div>
    </div>
    <Handle v-for="p in pins" :id="p.handle" :key="p.handle" :type="p.dir === 'in' ? 'target' : 'source'" :position="p.side === 'left' ? Position.Left : Position.Right" class="kir-pin" :class="[`kir-pin--${p.flow === 'ctrl' ? 'exec' : 'data'}`, { 'kir-pin--free': p.free }]" :style="pinStyle(p)" :title="`${p.dir} ${p.name}${p.type ? `: ${p.type}` : ''}`" />
  </div>
</template>

<script setup>
import { computed } from "vue"
import { Handle, Position } from "@vue-flow/core"

import { HEAD, ROW } from "@/graph/styles/card"
import { useDocumentStore } from "@/stores/document"
import LiteralWidget from "@/views/shared/LiteralWidget.vue"

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const PIN = 12
const ICON = {
  call: "i-carbon-function",
  defcall: "i-carbon-function-math",
  assign: "i-carbon-assignment",
  branch: "i-carbon-flow-connection",
  switch: "i-carbon-tree-view-alt",
  merge: "i-carbon-direction-merge",
  each: "i-carbon-repeat",
  parallel: "i-carbon-split",
  try: "i-carbon-warning-alt",
  inputs: "i-carbon-login",
  outputs: "i-carbon-logout",
}

const docStore = useDocumentStore()
const node = computed(() => props.data.node)
const g = computed(() => props.data.geom)
const pins = computed(() => g.value.ports.filter((p) => p.flow === "data" || props.data.exec))
const hints = computed(() =>
  Object.entries(node.value.hints || {})
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(" "),
)

const isWired = (port) => props.data.wired.includes(port)

function pinStyle(p) {
  return {
    left: `${p.x - PIN / 2}px`,
    top: `${p.y - PIN / 2}px`,
    right: "auto",
    bottom: "auto",
    transform: "none",
    "--pin-color": p.color,
  }
}

function commit(port, value) {
  docStore.setInputValue(node.value.id, port, value)
}
</script>
