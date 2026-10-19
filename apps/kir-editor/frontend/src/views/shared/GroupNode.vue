<template>
  <div class="kir-frame" :class="{ 'is-selected': selected }" :style="{ width: `${box.w}px`, height: `${box.h}px` }">
    <div class="kir-frame__title">
      <span class="i-carbon-data-share text-xs" />
      <span>@dataflow</span>
      <span class="kir-frame__count">{{ members }} statements, ordered by data</span>
    </div>
    <template v-if="data.exec !== false">
      <Handle v-for="p in box.ports" :id="p.handle" :key="p.handle" :type="p.dir === 'in' ? 'target' : 'source'" :position="POSITION[p.side]" class="kir-pin kir-pin--exec" :style="pinStyle(p)" />
    </template>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { Handle, Position } from "@vue-flow/core"

/** A `@dataflow:` block on the control chain, drawn as a group around its members. */
const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const PIN = 12
const POSITION = { top: Position.Top, bottom: Position.Bottom, left: Position.Left, right: Position.Right }
const box = computed(() => props.data.box)
const members = computed(() => props.data.node.props?.members?.length ?? 0)

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
</script>
