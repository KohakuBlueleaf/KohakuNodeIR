<template>
  <div class="h-full overflow-auto p-4 bg-warm-50 dark:bg-warm-950">
    <div v-if="!outline" class="text-sm text-warm-500">No program yet.</div>
    <div v-else class="flex flex-col gap-1.5 max-w-3xl">
      <div v-if="outline.uses.length || outline.mode" class="flex flex-wrap gap-1.5 mb-2">
        <span v-for="u in outline.uses" :key="u.library" class="kir-block kir-block--directive">@use "{{ u.library }}"<template v-if="u.alias"> as {{ u.alias }}</template></span>
        <span v-if="outline.mode" class="kir-block kir-block--directive">@mode {{ outline.mode }}</span>
      </div>
      <BlockItem v-for="(s, i) in outline.body" :key="i" :stmt="s" />
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"

import BlockItem from "@/components/blocks/BlockItem.vue"
import { useDocumentStore } from "@/stores/document"

const docStore = useDocumentStore()
const outline = computed(() => docStore.outline)
</script>

<style>
.kir-block {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 28px;
  padding: 0.2rem 0.7rem;
  border-radius: 7px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: #fff;
  box-shadow: inset 0 -2px 0 rgb(0 0 0 / 0.18);
  cursor: pointer;
  width: fit-content;
  max-width: 100%;
  white-space: pre-wrap;
  word-break: break-word;
}
.kir-block:hover {
  filter: brightness(1.08);
}
.kir-block--assign {
  background: var(--kt-color-amber);
}
.kir-block--call {
  background: var(--kt-color-sapphire);
}
.kir-block--branch,
.kir-block--switch,
.kir-block--jump,
.kir-block--parallel,
.kir-block--each,
.kir-block--namespace {
  background: var(--kt-color-iolite);
}
.kir-block--try {
  background: var(--kt-color-coral);
}
.kir-block--dataflow {
  background: var(--kt-color-aquamarine);
}
.kir-block--def {
  background: var(--kt-color-taaffeite);
}
.kir-block--typehint,
.kir-block--directive {
  background: var(--kt-color-warm-500);
}
.kir-cblock {
  display: flex;
  flex-direction: column;
  width: fit-content;
  min-width: 14rem;
  max-width: 100%;
}
.kir-cblock__arm {
  display: flex;
}
.kir-cblock__spine {
  width: 14px;
  flex-shrink: 0;
}
.kir-cblock__body {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.35rem 0 0.35rem 0.4rem;
  min-height: 1.6rem;
}
.kir-cblock__foot {
  height: 10px;
  border-radius: 0 0 7px 7px;
}
.kir-cblock__label {
  border-radius: 7px 7px 7px 0;
}
.kir-cblock__label--mid {
  border-radius: 0 7px 7px 0;
}
</style>
