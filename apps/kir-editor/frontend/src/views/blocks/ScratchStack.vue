<template>
  <div class="sb-stack" :class="{ 'sb-stack--empty': !list.length }">
    <template v-for="(item, i) in list" :key="keyOf(item, i)">
      <div class="sb-drop" :class="{ 'is-over': over === i }" @dragover.prevent="over = i" @dragleave="over = -1" @drop.prevent="drop($event, i)" />
      <ScratchBlock :item="item" :list="list" :loops="loops" />
    </template>
    <div class="sb-drop sb-drop--end" :class="{ 'is-over': over === list.length }" @dragover.prevent="over = list.length" @dragleave="over = -1" @drop.prevent="drop($event, list.length)">
      <span v-if="!list.length" class="sb-drop__hint">drop blocks here</span>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue"

import { ITEM_MIME, NODE_MIME, dragState, moveItem } from "@/program/edit"
import { useStatementTree } from "@/program/useStatementTree"
import ScratchBlock from "@/views/blocks/ScratchBlock.vue"

/** A stack of blocks, with a drop zone before each block and at the end. */
const props = defineProps({
  list: { type: Array, required: true },
  /** Labels of the loops around this stack (a jump to one is a "continue"). */
  loops: { type: Array, default: () => [] },
})

defineOptions({ name: "ScratchStack" })

const ctx = useStatementTree()
const over = ref(-1)

// Items have no ids; their statement objects are stable while the tree lives.
const ids = new WeakMap()
let next = 0
function keyOf(item, i) {
  const s = item.s || item.ns
  if (!s) return i
  if (!ids.has(s)) ids.set(s, `b${next++}`)
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
