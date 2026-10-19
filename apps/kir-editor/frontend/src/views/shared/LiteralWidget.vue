<template>
  <button v-if="mode === 'bool'" class="kir-widget kir-widget--bool nodrag" :class="{ 'is-on': value === true }" :title="`${value === true ? 'True' : 'False'} (click to switch)`" @click.stop="emit('commit', value !== true)">
    <span class="kir-widget__knob" />{{ value === true ? "True" : value === false ? "False" : "—" }}
  </button>
  <input v-else v-model="draft" class="kir-widget nodrag nowheel" :class="[`kir-widget--${mode}`, { 'is-bad': bad }]" :placeholder="placeholder" :inputmode="mode === 'number' ? 'decimal' : 'text'" spellcheck="false" :title="bad || hint" @keydown.enter.prevent="commit" @keydown.stop @blur="commit" />
</template>

<script setup>
import { computed, ref, watch } from "vue"

import { formatLiteral, parseLiteral } from "@/graph/literal"

/**
 * An input box for one literal (ComfyUI-style widget): a switch for bool, a
 * number field, a text field for str, and KIR literal syntax for anything
 * else (lists, dicts, None). Commits on Enter or blur; an empty box commits
 * `undefined` (no literal).
 */
const props = defineProps({
  value: { default: undefined },
  type: { type: String, default: null },
  placeholder: { type: String, default: "" },
})
const emit = defineEmits(["commit"])

const head = computed(() => (props.type || "").replace(/\?$/, "").split("[")[0])
const mode = computed(() => {
  const v = props.value
  if (typeof v === "boolean" || head.value === "bool") return "bool"
  if (typeof v === "number" || head.value === "int" || head.value === "float") return "number"
  if (typeof v === "string" || head.value === "str") return "text"
  return "literal"
})
const hint = computed(() => (mode.value === "literal" ? "KIR literal: 1, 'a', [1, 2], {'k': 1}, None" : ""))

const shown = () => {
  if (props.value === undefined) return ""
  if (mode.value === "text" && typeof props.value === "string") return props.value
  if (mode.value === "number" && typeof props.value === "number") return String(props.value)
  return formatLiteral(props.value)
}
const draft = ref(shown())
const bad = ref("")
watch(() => [props.value, mode.value], () => {
  draft.value = shown()
  bad.value = ""
})

function parse(text) {
  const t = text.trim()
  if (t === "") return undefined
  if (mode.value === "text") return text
  if (mode.value === "number") {
    const n = Number(t)
    if (!Number.isFinite(n)) throw new Error("not a number")
    return n
  }
  return parseLiteral(t)
}

function commit() {
  if (draft.value === shown()) return
  try {
    const v = parse(draft.value)
    bad.value = ""
    emit("commit", v)
  } catch (e) {
    bad.value = String(e.message || e)
  }
}
</script>
