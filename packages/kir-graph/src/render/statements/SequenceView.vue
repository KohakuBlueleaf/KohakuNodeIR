<template>
  <div ref="scroller" class="kg-sequence" @click="state.select?.(null)">
    <div ref="content" class="kg-sequence__content">
      <svg class="kg-sequence__wires" :width="size.w" :height="size.h">
        <path v-for="(w, i) in wires" :key="i" :d="w.d" :style="{ stroke: w.color }" class="kg-sequence__wire" />
      </svg>
      <section class="kg-script">
        <div class="kg-start" :title="model.name === 'main' ? 'the program starts here' : `@def ${model.name}`">
          <Icon :name="model.name === 'main' ? 'play-filled-alt' : 'function-math'" />
          <span v-if="model.name !== 'main'" class="kg-start__name">{{ model.name }}</span>
          <span v-for="p in params" :key="p.port" class="kg-plug" :data-wr="p.name" :style="{ '--kg-plug': `var(--kg-ev-${typeKind(p.type)})` }">{{ p.name }}</span>
        </div>
        <div class="kg-beam">
          <Tile v-for="(it, i) in items" :key="it.node.id + i" :item="it" :model="model" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { binds } from "./describe.js"
import { statementTree } from "../../model/tree.js"
import { typeKind } from "../../model/types.js"
import Icon from "../Icon.vue"
import { useGraphState } from "../overlay.js"
import Tile from "./Tile.vue"

/**
 * LEGO EV3 style: a sequence beam of tiles, left to right, with parameter
 * boxes below each tile and output plugs; containers stack their lanes. Data
 * wires run under the tiles from the plug that writes a name to every slot
 * reading it after it, coloured by the writer's type (number, logic, text,
 * other).
 */
const props = defineProps({ model: { type: Object, required: true } })

const state = useGraphState()
const tree = computed(() => statementTree(props.model))
const items = computed(() => tree.value.filter((it) => it.node.kind !== "inputs"))
const params = computed(() => {
  const inputs = tree.value.find((it) => it.node.kind === "inputs")
  return inputs ? binds(props.model, inputs.node).map((b) => ({ ...b, name: b.port })) : []
})

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
    let from = null
    for (const w of writers) if (w.dataset.wr === name && w.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING) from = w
    if (!from) continue
    const a = from.getBoundingClientRect()
    const b = r.getBoundingClientRect()
    const x1 = a.left + a.width / 2 - base.left
    const y1 = a.bottom - base.top
    const x2 = b.left + b.width / 2 - base.left
    const y2 = b.bottom - base.top
    const dip = Math.max(y1, y2) + 16
    out.push({ d: `M ${x1} ${y1} C ${x1} ${dip} ${x2} ${dip} ${x2} ${y2}`, color: `var(--kg-ev-${from.dataset.kind || "other"})` })
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
  if (content.value) observer.observe(content.value)
  schedule()
})
onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(frame)
})
watch(() => [props.model, state.collapsed.value], schedule)
</script>
