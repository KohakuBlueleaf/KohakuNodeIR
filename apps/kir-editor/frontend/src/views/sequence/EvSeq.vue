<template>
  <div class="ev-seq" :class="{ 'ev-seq--empty': !list.length }">
    <template v-for="(item, i) in list" :key="keyOf(item, i)">
      <div class="ev-drop" :class="{ 'is-over': over === i }" @dragover.prevent="over = i" @dragleave="over = -1" @drop.prevent="drop($event, i)" />
      <EvBlock :item="item" :list="list" :loops="loops" />
    </template>
    <div class="ev-drop ev-drop--end" :class="{ 'is-over': over === list.length }" @dragover.prevent="over = list.length" @dragleave="over = -1" @drop.prevent="drop($event, list.length)">
      <span v-if="!list.length" class="ev-drop__hint">drop here</span>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue"

import { ITEM_MIME, NODE_MIME, dragState, moveItem } from "@/program/edit"
import { useStatementTree } from "@/program/useStatementTree"
import EvBlock from "@/views/sequence/EvBlock.vue"

/** A sequence beam: blocks left to right, with a drop zone before each block and at the end. */
const props = defineProps({
  list: { type: Array, required: true },
  loops: { type: Array, default: () => [] },
})

defineOptions({ name: "EvSeq" })

const ctx = useStatementTree()
const over = ref(-1)
const ids = new WeakMap()
let next = 0
function keyOf(item, i) {
  const s = item.s || item.ns
  if (!s) return i
  if (!ids.has(s)) ids.set(s, `e${next++}`)
  return ids.get(s)
}

function drop(event, index) {
  over.value = -1
  const spec = event.dataTransfer.getData(NODE_MIME)
  if (spec) {
    ctx.insert(JSON.parse(spec), props.list, index)
    return
  }
  const d = dragState.current
  if (event.dataTransfer.getData(ITEM_MIME) && d) {
    dragState.current = null
    if (moveItem(d.item, d.from, props.list, index)) ctx.commit()
  }
}
</script>
