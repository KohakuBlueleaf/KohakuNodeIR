<template>
  <span class="field">
    <span v-if="label" class="field__caption">{{ label }}</span>
    <span class="seg">
      <button v-for="[value, text] in options" :key="String(value)" class="seg__opt" :class="{ 'is-on': modelValue === value }" @click="emit('update:modelValue', value)">{{ text }}</button>
    </span>
  </span>
</template>

<script setup>
/** A captioned segmented control: `options` is a list of `[value, text]`. */
defineProps({ modelValue: { type: [String, Boolean, Number], default: null }, options: { type: Array, required: true }, label: { type: String, default: "" } })
const emit = defineEmits(["update:modelValue"])
</script>
