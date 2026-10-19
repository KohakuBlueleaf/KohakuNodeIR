<template>
  <input v-if="editing" ref="field" v-model="draft" class="sb-name sb-name--edit" :class="{ 'is-bad': bad }" :style="{ width: `${Math.max(3, draft.length + 1)}ch` }" spellcheck="false" :title="bad" @keydown.enter.prevent="commit" @keydown.esc="editing = false" @blur="commit" />
  <span v-else class="sb-name" :class="[`sb-name--${kind}`]" :title="title" draggable="true" @click.stop="edit" @dragstart.stop="onDrag">{{ value ?? "_" }}</span>
</template>

<script setup>
import { nextTick, ref } from "vue"

import { VAR_MIME } from "@/program/edit"

/**
 * A name a block writes (a variable, an output, a loop item) or a label it
 * names: click to rename; a variable can be dragged into a slot as a reporter.
 */
const props = defineProps({
  value: { type: String, default: null },
  kind: { type: String, default: "var" },
  allowEmpty: { type: Boolean, default: false },
  title: { type: String, default: "" },
})
const emit = defineEmits(["update"])

const editing = ref(false)
const draft = ref("")
const bad = ref("")
const field = ref(null)

async function edit() {
  draft.value = props.value ?? ""
  bad.value = ""
  editing.value = true
  await nextTick()
  field.value?.focus()
  field.value?.select()
}

function commit() {
  if (!editing.value) return
  const t = draft.value.trim()
  if (t === (props.value ?? "")) {
    editing.value = false
    return
  }
  if (!t && props.allowEmpty) {
    editing.value = false
    emit("update", null)
    return
  }
  if (!/^[A-Za-z_]\w*$/.test(t) || t.includes("__")) {
    bad.value = "a name: letters, digits, _ (no __)"
    return
  }
  editing.value = false
  emit("update", t)
}

function onDrag(event) {
  if (props.kind !== "var" || !props.value) return
  event.dataTransfer.setData(VAR_MIME, props.value)
  event.dataTransfer.effectAllowed = "copy"
}
</script>
