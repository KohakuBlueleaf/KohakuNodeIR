<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="kir-viewbar">
      <span class="kir-viewbar__title"><span class="i-carbon-chart-relationship" />Sequence</span>
      <KnobGroup label="lanes" knob="lanes" :options="KNOBS.lanes" />
      <span class="text-[10.5px] text-warm-500 hidden xl:inline">blocks run left → right · click a parameter box to edit · data wires run under the blocks</span>
    </div>
    <div ref="scroller" class="flex-1 overflow-auto ev-canvas" data-test="sequence-canvas">
      <div v-if="!ctx.tree.value" class="p-4 text-sm text-warm-500">No program yet.</div>
      <div v-else ref="content" class="ev-content">
        <svg class="ev-wires" :width="size.w" :height="size.h">
          <path v-for="(w, i) in wires" :key="i" :d="w.d" :stroke="w.color" class="ev-wire" />
        </svg>
        <section class="ev-script" data-script="main">
          <div class="ev-start" title="the program starts here">
            <span class="i-carbon-play-filled-alt" />
            <span v-for="u in ctx.tree.value.uses" :key="u.library" class="ev-start__use">{{ u.alias ? `${u.library} as ${u.alias}` : u.library }}</span>
          </div>
          <EvSeq :list="ctx.tree.value.body" />
        </section>
        <section v-for="(it, i) in ctx.tree.value.head" :key="`h${i}`" class="ev-script" :data-script="it.t === 'def' ? it.s.name : 'typehints'">
          <template v-if="it.t === 'def'">
            <div class="ev-start ev-start--define" :title="`@def ${it.s.name}`">
              <span class="i-carbon-function-math" />
              <span class="ev-start__name">{{ it.s.name }}</span>
              <span v-for="p in it.s.params" :key="p.name" class="ev-plug" :data-wr="p.name" :style="{ '--ev-color': colorOf(p.name) }" :title="p.type ? `${p.name}: ${p.type}` : p.name">{{ p.name }}</span>
            </div>
            <EvSeq :list="it.body" />
          </template>
          <EvSeq v-else :list="[it]" />
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from "vue"

import { provideStatementTree } from "@/program/useStatementTree"
import { useDocumentStore } from "@/stores/document"
import { useLibraryStore } from "@/stores/library"
import { KNOBS, useUiStore } from "@/stores/ui"
import KnobGroup from "@/views/shared/KnobGroup.vue"
import EvSeq from "@/views/sequence/EvSeq.vue"
import { EV_COLOR, nameKinds } from "@/views/sequence/evTypes"

/**
 * LEGO EV3 style: each script is a sequence beam of coloured blocks, left to
 * right, with parameter boxes along their bottoms and output plugs; loops,
 * switches, parallel arms and try / except are containers with lanes. Data
 * wires run under the blocks from the plug that writes a variable to every
 * box that reads it, coloured by kind (number yellow, logic green, text
 * orange, other grey).
 */
const ctx = provideStatementTree()
const docStore = useDocumentStore()
const lib = useLibraryStore()
const ui = useUiStore()

const sigOf = (name) => {
  const r = lib.resolveCall(name, docStore.doc)
  if (r?.kind === "node") return r.sig
  if (r?.kind === "def")
    return { inputs: (r.graph.params || []).map((p) => ({ name: p.name, type: p.type })), outputs: r.graph.outputs || [] }
  return null
}
const kinds = computed(() => (ctx.tree.value ? nameKinds(ctx.tree.value, sigOf) : new Map()))
provide("ev", { kinds, sigOf })

const colorOf = (name) => EV_COLOR[kinds.value.get(name) || "other"]

// ---------------------------------------------------------------- data wires
const scroller = ref(null)
const content = ref(null)
const wires = ref([])
const size = ref({ w: 0, h: 0 })

function measure() {
  const root = content.value
  if (!root) return
  const base = root.getBoundingClientRect()
  size.value = { w: root.scrollWidth, h: root.scrollHeight }
  const writers = [...root.querySelectorAll("[data-wr]")]
  const out = []
  for (const r of root.querySelectorAll("[data-rd]")) {
    const name = r.dataset.rd
    const script = r.closest("[data-script]")
    let from = null
    for (const w of writers) {
      if (w.dataset.wr !== name || w.closest("[data-script]") !== script) continue
      if (w.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING) from = w
    }
    if (!from) continue
    const a = from.getBoundingClientRect()
    const b = r.getBoundingClientRect()
    const x1 = a.left + a.width / 2 - base.left
    const y1 = a.bottom - base.top
    const x2 = b.left + b.width / 2 - base.left
    const y2 = b.bottom - base.top
    const dip = Math.max(y1, y2) + 18
    out.push({
      d: `M ${x1} ${y1} C ${x1} ${dip} ${x2} ${dip} ${x2} ${y2}`,
      color: colorOf(name),
    })
  }
  wires.value = out
}

let frame = 0
function schedule() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => nextTick(measure))
}

let observer = null
onMounted(() => {
  observer = new ResizeObserver(schedule)
  if (scroller.value) observer.observe(scroller.value)
  schedule()
})
onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(frame)
})
watch(() => [ctx.tree.value, ui.lanes], schedule, { deep: true })
watch(content, (el) => {
  if (el && observer) observer.observe(el)
  schedule()
})

function addAtCenter(spec) {
  if (ctx.tree.value) ctx.insert(spec, ctx.tree.value.body, ctx.tree.value.body.length)
}

defineExpose({ addAtCenter })
</script>
