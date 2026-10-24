<template>
  <Handle
    v-for="p in ports"
    :id="p.handle"
    :key="p.handle"
    :type="p.dir === 'in' ? 'target' : 'source'"
    :position="POSITION[p.side]"
    :connectable="false"
    class="kg-pin"
    :class="[`kg-pin--${p.flow}`, `kg-pin--${p.side}`, { 'kg-pin--any': p.name === '*' }]"
    :style="{ left: `${p.x}px`, top: `${p.y}px`, '--kg-pin': p.color }"
    :title="`${p.dir} ${p.name}${p.type ? `: ${p.type}` : ''}`"
  />
</template>

<script setup>
import { Handle, Position } from "@vue-flow/core"

/** The pins of an element, at the positions its geometry gives (centred on them by CSS). */
defineProps({ ports: { type: Array, required: true } })

const POSITION = { top: Position.Top, bottom: Position.Bottom, left: Position.Left, right: Position.Right }
</script>
