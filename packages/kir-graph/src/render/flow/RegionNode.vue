<template>
  <div class="kg-region" :class="[`kg-region--${data.tone}`, marks]" :style="{ width: `${data.w}px`, height: `${data.h}px`, ...heat }">
    <div class="kg-region__head" :style="{ height: `${REGION_HEAD}px` }">
      <button class="kg-region__toggle nodrag" title="Collapse this region" @click.stop="state.toggle?.(data.rid)">
        <Icon name="chevron-down" />
      </button>
      <Icon :name="kindIcon(data.tone)" class="kg-region__icon" />
      <span class="kg-region__title">{{ data.title }}</span>
      <OverlayMarks :entry="entry" placement="inline" />
    </div>
  </div>
  <Pins v-if="data.ports.length" :ports="data.ports" fixed />
</template>

<script setup>
import { computed } from "vue"

import { REGION_HEAD } from "../../geometry/region.js"
import Icon from "../Icon.vue"
import { kindIcon } from "../kinds.js"
import OverlayMarks from "../OverlayMarks.vue"
import { heatStyle, useGraphState } from "../overlay.js"
import { markClasses } from "./marks.js"
import Pins from "./Pins.vue"

/**
 * A region box behind its statements: a branch arm, loop or each body, try or
 * handler, or a dataflow block (whose box is its owner node, with its control
 * pins). The header button collapses it.
 */
const props = defineProps({ id: { type: String, required: true }, data: { type: Object, required: true } })
// vue-flow hands every node its state as attributes; a fragment root takes only id and data
defineOptions({ inheritAttrs: false })

const state = useGraphState()
const entry = computed(() => state.regions.get(props.data.rid) || null)
const heat = computed(() => heatStyle(entry.value))
const marks = computed(() => markClasses(state, props.data.rid, props.data.ownerId, entry.value))
</script>
