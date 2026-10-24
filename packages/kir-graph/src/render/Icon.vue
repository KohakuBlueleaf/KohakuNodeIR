<template>
  <svg class="kg-icon" :viewBox="`0 0 ${icon.size} ${icon.size}`" aria-hidden="true" v-html="icon.body" />
</template>

<script setup>
import { computed } from "vue"

import { ICONS } from "./icons.js"

/** A Carbon icon by name (render/icons.js), sized by the font. */
const props = defineProps({ name: { type: String, required: true } })
const icon = computed(() => ICONS[props.name] || ICONS.function)
</script>
