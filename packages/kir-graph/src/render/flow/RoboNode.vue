<template>
  <div class="kg-robo" :class="[`kg-robo--${g.shape}`, marks]" :style="{ width: `${g.w}px`, height: `${g.h}px`, ...heat }" :title="tooltip">
    <svg class="kg-robo__svg" :width="g.w" :height="g.h" :viewBox="`0 0 ${g.w} ${g.h}`">
      <clipPath v-if="hot" :id="clipId">
        <path v-if="path" :d="path" />
        <rect v-else x="0" y="0" :width="g.w" :height="g.h" :rx="RADIUS[g.shape] ?? 3" />
      </clipPath>
      <path v-if="path" :d="path" class="kg-robo__shape" />
      <template v-else-if="g.shape === 'defcall'">
        <rect x="0.75" y="0.75" :width="g.w - 1.5" :height="g.h - 1.5" rx="3" class="kg-robo__shape" />
        <rect x="4" y="4" :width="g.w - 8" :height="g.h - 8" rx="2" class="kg-robo__inner" />
      </template>
      <rect v-else x="0.75" y="0.75" :width="g.w - 1.5" :height="g.h - 1.5" :rx="RADIUS[g.shape] ?? 3" class="kg-robo__shape" />
      <!-- Heat fills the outline from the left, as far as the heat goes -->
      <rect v-if="hot" :clip-path="`url(#${clipId})`" x="0" y="0" :width="g.w * Math.min(1, entry.heat)" :height="g.h" class="kg-robo__heat" />
      <line v-if="g.head && g.h > g.head + 4" x1="1" :x2="g.w - 1" :y1="g.head" :y2="g.head" class="kg-robo__rule" />
      <text v-for="(t, i) in g.texts" :key="i" :x="t.x" :y="t.y" :text-anchor="t.anchor" :class="`kg-robo__text kg-robo__text--${t.cls}`">{{ t.text }}</text>
    </svg>
    <OverlayMarks :entry="entry" />
  </div>
  <Pins :ports="g.ports" />
</template>

<script setup>
import { computed } from "vue"

import { shapePath } from "../../geometry/robo.js"
import OverlayMarks from "../OverlayMarks.vue"
import { heatStyle, useGraphState } from "../overlay.js"
import { markClasses, nodeTooltip } from "./marks.js"
import Pins from "./Pins.vue"

/** One flowchart element (ROBO Pro style); geometry from geometry/robo.js. */
const props = defineProps({ id: { type: String, required: true }, data: { type: Object, required: true } })
// vue-flow hands every node its state as attributes; a fragment root takes only id and data
defineOptions({ inheritAttrs: false })

const RADIUS = { value: 13, start: 15, end: 15, variable: 2, bar: 3 }
const clipId = `kg-robo-clip-${++clips}`

const state = useGraphState()
const node = computed(() => props.data.node)
const g = computed(() => props.data.geom)
const path = computed(() => shapePath(g.value))
const entry = computed(() => state.nodes.get(props.data.key) || null)
const heat = computed(() => heatStyle(entry.value))
const hot = computed(() => (entry.value?.heat ?? 0) > 0)
const tooltip = computed(() => nodeTooltip(node.value))
const marks = computed(() => markClasses(state, props.data.key, node.value.id, entry.value, node.value))
</script>

<script>
let clips = 0
</script>
