<template>
  <Handle
    v-for="p in ports"
    :id="p.handle"
    :key="p.handle"
    :type="p.dir === 'in' ? 'target' : 'source'"
    :position="POSITION[p.side]"
    :connectable="wirable"
    :is-valid-connection="wirable ? state.validConnection : undefined"
    class="kg-pin"
    :class="[`kg-pin--${p.flow}`, `kg-pin--${p.side}`, { 'kg-pin--any': p.name === '*', 'kg-pin--wirable': wirable }]"
    :style="{ left: `${p.x}px`, top: `${p.y}px`, '--kg-pin': p.color }"
    :title="`${p.dir} ${p.name}${p.type ? `: ${p.type}` : ''}`"
  />
</template>

<script setup>
import { computed } from "vue"
import { Handle, Position } from "@vue-flow/core"

import { useGraphState } from "../overlay.js"

/**
 * The pins of an element, at the positions its geometry gives (centred on them
 * by CSS). While the graph is editable a statement's pins take new wires;
 * `fixed` pins (region and collapsed boxes) never do.
 */
const props = defineProps({ ports: { type: Array, required: true }, fixed: { type: Boolean, default: false } })

const POSITION = { top: Position.Top, bottom: Position.Bottom, left: Position.Left, right: Position.Right }
const state = useGraphState()
const wirable = computed(() => !props.fixed && !!state.editable?.value)
</script>
