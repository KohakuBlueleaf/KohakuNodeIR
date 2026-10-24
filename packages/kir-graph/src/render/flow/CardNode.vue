<template>
  <!-- Variable / literal pill -->
  <div v-if="g.shape === 'pill'" class="kg-pill" :class="[`kg-pill--${g.variant}`, marks]" :style="{ width: `${g.w}px`, height: `${g.h}px`, ...heat }" :title="tooltip">
    <span v-if="g.param" class="kg-pill__tag">{{ g.param === "input" ? "in" : "out" }}</span>
    <Icon v-else-if="g.variant !== 'value'" :name="g.variant === 'get' ? 'download' : 'upload'" class="kg-pill__icon" />
    <span class="kg-pill__text">{{ g.title }}</span>
    <OverlayMarks :entry="entry" />
  </div>

  <!-- Card -->
  <div v-else class="kg-card" :class="[`kg-card--${g.variant}`, `kg-accent--${g.accent}`, marks]" :style="{ width: `${g.w}px`, height: `${g.h}px`, ...heat }" :title="tooltip">
    <div class="kg-card__head" :style="{ height: `${g.head}px` }">
      <Icon :name="kindIcon(g.variant)" class="kg-card__icon" />
      <span class="kg-card__title">{{ g.title }}</span>
      <span v-if="node.hints" class="kg-card__hint" />
    </div>
    <div v-for="(row, i) in g.rows" :key="i" class="kg-card__row" :style="{ top: `${row.y - ROW / 2}px`, height: `${ROW}px` }">
      <span v-if="row.left" class="kg-card__label" :class="{ 'is-ctrl': row.left.flow === 'ctrl', 'is-literal': row.left.literal }">{{ row.left.label }}</span>
      <span v-if="row.right" class="kg-card__label kg-card__label--right" :class="{ 'is-ctrl': row.right.flow === 'ctrl' }">{{ row.right.label }}</span>
    </div>
    <span v-for="(c, i) in g.ctrlLabels || []" :key="`c${i}`" class="kg-card__label is-ctrl kg-card__ctrl" :style="{ left: `${c.x}px`, top: `${c.y}px` }">{{ c.label }}</span>
    <OverlayMarks :entry="entry" />
  </div>
  <Pins :ports="g.ports" />
</template>

<script setup>
import { computed } from "vue"

import { ROW } from "../../geometry/card.js"
import Icon from "../Icon.vue"
import { kindIcon } from "../kinds.js"
import OverlayMarks from "../OverlayMarks.vue"
import { heatStyle, useGraphState } from "../overlay.js"
import Pins from "./Pins.vue"
import { markClasses, nodeTooltip } from "./marks.js"

/** A node-view card (or variable / literal pill); geometry from geometry/card.js. */
const props = defineProps({ id: { type: String, required: true }, data: { type: Object, required: true } })

const state = useGraphState()
const node = computed(() => props.data.node)
const g = computed(() => props.data.geom)
const entry = computed(() => state.nodes.get(props.data.key) || null)
const heat = computed(() => heatStyle(entry.value))
const tooltip = computed(() => nodeTooltip(node.value))
const marks = computed(() => markClasses(state, props.data.key, node.value.id, entry.value, node.value))
</script>
