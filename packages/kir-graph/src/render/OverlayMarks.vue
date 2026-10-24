<template>
  <div v-if="entry && (entry.status || entry.badges?.length || entry.note)" class="kg-marks" :class="`kg-marks--${placement}`">
    <span v-if="entry.status" class="kg-status" :class="`kg-status--${entry.status}`" :title="entry.status">
      <Icon :name="STATUS_ICON[entry.status] || 'circle-dash'" />
    </span>
    <span v-for="(b, i) in entry.badges || []" :key="i" class="kg-badge" :class="`kg-badge--${b.tone || 'muted'}`" :title="b.title || b.text">{{ b.text }}</span>
    <span v-if="entry.note" class="kg-note" :title="entry.note">{{ entry.note }}</span>
  </div>
</template>

<script setup>
import Icon from "./Icon.vue"
import { STATUS_ICON } from "./kinds.js"

/** An overlay entry's status, badges and note, drawn above an element (or inline in a statement view). */
defineProps({
  entry: { type: Object, default: null },
  placement: { type: String, default: "above" },
})
</script>
