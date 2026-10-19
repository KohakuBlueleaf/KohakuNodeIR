<template>
  <div class="kir-frame" :class="{ 'is-selected': selected }" :style="{ width: `${box.w}px`, height: `${box.h}px` }">
    <div class="kir-frame__title">
      <span class="i-carbon-data-share text-xs" />
      <span>@dataflow</span>
      <span class="kir-frame__count">{{ members }} statements, ordered by data</span>
    </div>
    <Handle v-for="p in box.ports" :id="p.handle" :key="p.handle" :type="p.dir === 'in' ? 'target' : 'source'" :position="p.side === 'top' ? Position.Top : Position.Bottom" class="kir-port kir-port--ctrl" :style="portStyle(p)" />
  </div>
</template>

<script setup>
import { computed } from "vue"
import { Handle, Position } from "@vue-flow/core"

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const PORT = 10
const box = computed(() => props.data.box)
const members = computed(() => props.data.node.props?.members?.length ?? 0)

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
</script>
