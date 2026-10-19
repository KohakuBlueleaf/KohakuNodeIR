<template>
  <input v-if="editing" ref="field" v-model="draft" class="sb-slot sb-slot--edit" :class="[`sb-slot--${shape}`, { 'is-bad': bad }]" :style="{ width: `${Math.max(3, draft.length + 1)}ch` }" spellcheck="false" :title="bad" @keydown.enter.prevent="commit" @keydown.esc="editing = false" @blur="commit" />
  <span v-else-if="expr && 'name' in expr" class="sb-reporter" :class="{ 'sb-reporter--hex': shape === 'hex' }" title="a variable (click to edit, drop another variable here)" @click.stop="edit" @dragover.prevent @drop.stop="onDrop">{{ expr.name }}</span>
  <span v-else class="sb-slot" :class="[`sb-slot--${shape}`, { 'sb-slot--empty': !expr }]" :title="expr ? 'click to edit; a name makes it a variable' : placeholder" @click.stop="edit" @dragover.prevent @drop.stop="onDrop">{{ expr ? shown : placeholder }}</span>
</template>

<script setup>
import { computed, nextTick, ref } from "vue"

import { exprFromText, exprText } from "@/program/create"
import { VAR_MIME } from "@/program/edit"

/**
 * An input slot of a block: a round slot for a number or text, a hexagonal
 * one for a condition, or a variable reporter (an orange oval) when it holds
 * a name. Click to type a literal or a name; drop a variable reporter on it.
 */
const props = defineProps({
  expr: { type: Object, default: null },
  shape: { type: String, default: "round" },
  placeholder: { type: String, default: "" },
})
const emit = defineEmits(["update"])

const editing = ref(false)
const draft = ref("")
const bad = ref("")
const field = ref(null)

const shown = computed(() => {
  const v = props.expr?.lit
  return typeof v === "string" ? `"${v}"` : exprText(props.expr)
})

async function edit() {
  draft.value = exprText(props.expr)
  bad.value = ""
  editing.value = true
  await nextTick()
  field.value?.focus()
  field.value?.select()
}

function commit() {
  if (!editing.value) return
  if (draft.value === exprText(props.expr)) {
    editing.value = false
    return
  }
  try {
    const e = exprFromText(draft.value)
    editing.value = false
    emit("update", e)
  } catch (err) {
    bad.value = String(err.message || err)
  }
}

function onDrop(event) {
  const name = event.dataTransfer.getData(VAR_MIME)
  if (name) emit("update", { name })
}
</script>
