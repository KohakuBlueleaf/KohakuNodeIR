<template>
  <div class="kg-collapsed" :class="[`kg-region--${data.tone}`, marks]" :style="{ width: `${g.w}px`, height: `${g.h}px`, ...heat }" :title="`${g.title}\n${g.sub}`">
    <div class="kg-collapsed__head">
      <button class="kg-region__toggle nodrag" title="Expand this region" @click.stop="state.toggle?.(data.rid)">
        <Icon name="chevron-right" />
      </button>
      <Icon :name="kindIcon(data.tone)" class="kg-region__icon" />
      <span class="kg-region__title">{{ g.title }}</span>
    </div>
    <div class="kg-collapsed__sub">{{ g.sub }}</div>
    <OverlayMarks :entry="entry" />
  </div>
  <Pins :ports="g.ports" fixed />
</template>

<script setup>
import { computed } from "vue"

import Icon from "../Icon.vue"
import { kindIcon, worstStatus } from "../kinds.js"
import OverlayMarks from "../OverlayMarks.vue"
import { heatStyle, useGraphState } from "../overlay.js"
import { markClasses } from "./marks.js"
import Pins from "./Pins.vue"

/**
 * A collapsed region: one box for every statement inside it. Its overlay is
 * the region's own entry, else the hottest heat and worst status of the
 * statements it holds.
 */
const props = defineProps({ id: { type: String, required: true }, data: { type: Object, required: true } })
// vue-flow hands every node its state as attributes; a fragment root takes only id and data
defineOptions({ inheritAttrs: false })

const state = useGraphState()
const g = computed(() => props.data.geom)
const entry = computed(() => {
  const own = state.regions.get(props.data.rid)
  if (own) return own
  let heat = null
  let status = null
  let n = 0
  for (const key of props.data.keys) {
    const e = state.nodes.get(key)
    if (!e) continue
    n++
    if (e.heat != null) heat = Math.max(heat ?? 0, e.heat)
    if (e.status) status = status ? worstStatus(status, e.status) : e.status
  }
  return n ? { heat, status, badges: [{ text: `${n} live`, tone: "muted" }] } : null
})
const heat = computed(() => heatStyle(entry.value))
const marks = computed(() => markClasses(state, props.data.rid, props.data.rid, entry.value))
</script>
