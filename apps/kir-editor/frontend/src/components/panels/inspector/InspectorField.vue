<template>
  <label class="flex flex-col gap-0.5 min-w-0">
    <span v-if="label" class="text-[10.5px] text-warm-500">{{ label }}</span>
    <input v-model="draft" class="input-field" :class="{ '!border-coral': error }" :placeholder="placeholder" spellcheck="false" @keydown.enter="commit" @blur="commit" />
    <span v-if="error" class="text-[10.5px] text-coral">{{ error }}</span>
  </label>
</template>

<script setup>
import { ref, watch } from "vue"

/** A text input that commits on Enter or blur; `commit` may throw to reject the text. */
const props = defineProps({
  label: { type: String, default: "" },
  value: { type: String, default: "" },
  placeholder: { type: String, default: "" },
  commit: { type: Function, required: true },
})

const draft = ref(props.value)
const error = ref("")

watch(
  () => props.value,
  (v) => {
    draft.value = v
    error.value = ""
  },
)

function commit() {
  if (draft.value === props.value) return
  try {
    props.commit(draft.value)
    error.value = ""
  } catch (e) {
    error.value = String(e.message || e)
  }
}
</script>
