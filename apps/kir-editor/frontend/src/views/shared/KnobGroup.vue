<template>
  <div class="kir-knob" :data-knob="knob">
    <span class="kir-knob__label">{{ label }}</span>
    <button v-for="o in options" :key="o" class="kir-knob__opt" :class="{ 'is-on': ui[knob] === o }" :data-value="o" @click="ui.setKnob(knob, o)">{{ o }}</button>
  </div>
</template>

<script setup>
import { useUiStore } from "@/stores/ui"

/** A segmented switch for one persisted view knob (ui store). */
defineProps({
  label: { type: String, required: true },
  knob: { type: String, required: true },
  options: { type: Array, required: true },
})

const ui = useUiStore()
</script>
