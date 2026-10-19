<template>
  <!-- A statement holding statements: a C-block, one arm per nested block. -->
  <div v-if="stmt.slots" class="kir-cblock">
    <template v-for="(slot, i) in stmt.slots" :key="i">
      <div :class="['kir-block', `kir-block--${stmt.kind}`, i === 0 ? 'kir-cblock__label' : 'kir-cblock__label--mid']" :title="where" @click="reveal">
        <span :class="ICON[stmt.kind]" class="text-[11px] opacity-80" />
        <span>{{ i === 0 ? stmt.text : `${slot.label}:` }}</span>
      </div>
      <div class="kir-cblock__arm">
        <div :class="['kir-cblock__spine', `kir-block--${stmt.kind}`]" />
        <div class="kir-cblock__body">
          <BlockItem v-for="(s, j) in slot.body" :key="j" :stmt="s" />
          <span v-if="!slot.body.length" class="text-[11px] text-warm-400 font-mono italic">empty</span>
        </div>
      </div>
    </template>
    <div :class="['kir-cblock__foot', `kir-block--${stmt.kind}`]" />
  </div>
  <div v-else-if="stmt.kind === 'typehint'" class="kir-block kir-block--typehint" :title="where" @click="reveal">
    <span class="i-carbon-text-annotation-toggle text-[11px]" />
    <span>@typehint: {{ stmt.entries.join("  ") }}</span>
  </div>
  <div v-else :class="['kir-block', `kir-block--${stmt.kind}`]" :title="where" @click="reveal">
    <span :class="ICON[stmt.kind]" class="text-[11px] opacity-80" />
    <span>{{ stmt.text }}</span>
    <span v-if="stmt.hint" class="opacity-75 text-[10.5px]">@hint {{ pairs(stmt.hint) }}</span>
  </div>
</template>

<script setup>
import { computed } from "vue"

import { useUiStore } from "@/stores/ui"

defineOptions({ name: "BlockItem" })

const props = defineProps({ stmt: { type: Object, required: true } })
const ui = useUiStore()

const ICON = {
  assign: "i-carbon-assignment",
  call: "i-carbon-function",
  branch: "i-carbon-flow-connection",
  switch: "i-carbon-tree-view-alt",
  jump: "i-carbon-redo",
  parallel: "i-carbon-split",
  each: "i-carbon-repeat",
  namespace: "i-carbon-tag",
  dataflow: "i-carbon-data-share",
  try: "i-carbon-warning-alt",
  def: "i-carbon-function-math",
}

const where = computed(() => (props.stmt.line ? `line ${props.stmt.line}` : ""))

const pairs = (o) => Object.entries(o).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" ")

function reveal() {
  ui.revealLine(props.stmt.line)
}
</script>
