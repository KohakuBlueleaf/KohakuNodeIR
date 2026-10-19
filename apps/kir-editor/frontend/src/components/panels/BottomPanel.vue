<template>
  <section data-test="bottom-panel" class="flex flex-col bg-white dark:bg-warm-900 border-t border-warm-200 dark:border-warm-800 min-h-0">
    <div class="flex items-center gap-1 h-8 px-2 border-b border-warm-200 dark:border-warm-800 shrink-0">
      <button v-for="t in TABS" :key="t.id" class="kir-tab" :class="{ 'kir-tab--on': ui.bottomTab === t.id }" @click="ui.showBottom(t.id)">
        <span :class="t.icon" class="text-xs" />{{ t.label }}
        <span v-if="t.id === 'problems' && docStore.diagnostics.length" class="kir-count" :class="docStore.errorCount ? 'bg-coral' : 'bg-amber'">{{ docStore.diagnostics.length }}</span>
      </button>
      <span class="flex-1" />
      <button class="btn-icon" title="Close panel" @click="ui.bottomOpen = false"><span class="i-carbon-chevron-down text-sm" /></button>
    </div>

    <div class="flex-1 overflow-auto min-h-0 text-xs">
      <!-- Problems -->
      <div v-if="ui.bottomTab === 'problems'">
        <div v-if="docStore.transportError" class="px-3 py-2 text-coral font-mono">backend unreachable: {{ docStore.transportError }}</div>
        <div v-if="!docStore.diagnostics.length" class="px-3 py-2 text-warm-500 flex items-center gap-1.5"><span class="i-carbon-checkmark-filled text-sage" />No problems.</div>
        <button v-for="(d, i) in docStore.diagnostics" :key="i" class="w-full flex items-start gap-2 px-3 py-1 text-left hover:bg-warm-100 dark:hover:bg-warm-800" @click="ui.revealLine(d.line)">
          <span :class="d.severity === 'error' ? 'i-carbon-error-filled text-coral' : 'i-carbon-warning-filled text-amber'" class="mt-0.5 shrink-0" />
          <span class="font-mono font-semibold shrink-0 w-14">{{ d.code }}</span>
          <span class="flex-1 text-warm-700 dark:text-warm-200 whitespace-pre-wrap">{{ d.message }}</span>
          <span v-if="d.line" class="font-mono text-warm-400 shrink-0">line {{ d.line }}</span>
        </button>
      </div>

      <!-- Run -->
      <div v-else-if="ui.bottomTab === 'run'" class="p-3">
        <div v-if="!docStore.runResult" class="text-warm-500">Run executes the text on the reference interpreter with the demo node library.</div>
        <template v-else>
          <div class="flex items-center gap-2 mb-2">
            <span :class="docStore.runResult.ok ? 'chip-aqua' : 'chip-coral'">{{ docStore.runResult.ok ? "finished" : "failed" }}</span>
            <span class="text-warm-500">{{ Object.keys(docStore.runResult.values).length }} final values</span>
          </div>
          <div class="grid gap-3" style="grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)">
            <div>
              <div class="section-title mb-1">stdout</div>
              <pre class="font-mono text-[11.5px] bg-warm-50 dark:bg-warm-950 rounded-md p-2 min-h-8 whitespace-pre-wrap">{{ docStore.runResult.stdout || "(nothing printed)" }}</pre>
            </div>
            <div>
              <div class="section-title mb-1">final values</div>
              <table class="w-full font-mono text-[11.5px]">
                <tr v-for="(v, k) in docStore.runResult.values" :key="k" class="border-b border-warm-100 dark:border-warm-800">
                  <td class="pr-3 py-0.5 text-warm-600 dark:text-warm-300 align-top">{{ k }}</td>
                  <td class="py-0.5 break-all">{{ formatLiteral(v) }}</td>
                </tr>
              </table>
            </div>
          </div>
        </template>
      </div>

      <!-- Lowered: the program after the selected optimization passes -->
      <div v-else class="p-3">
        <div class="flex flex-wrap items-center gap-1.5 mb-2">
          <span class="section-title mr-1">passes</span>
          <button v-for="p in docStore.passCatalog" :key="p.name" class="kir-pass" :class="{ 'kir-pass--on': docStore.passesOn.includes(p.name) }" :title="`${p.doc}${p.needs.length ? `\nneeds: ${p.needs.join(', ')}` : ''}`" @click="docStore.togglePass(p.name)">{{ p.name }}</button>
          <span class="text-[11px] text-warm-500 ml-1">{{ passSummary }} · Lower and Run use this selection</span>
        </div>
        <div v-if="!docStore.lowerResult" class="text-warm-500">Lower shows the program after the selected passes (all of them: no @def, no each, versioned names, straight runs grouped) and its hashes.</div>
        <template v-else-if="docStore.lowerResult.lowered != null">
          <div class="flex flex-wrap gap-x-4 gap-y-1 mb-2 font-mono text-[11px]">
            <span><span class="text-warm-500">semantic</span> {{ docStore.lowerResult.semantic_hash }}</span>
            <span><span class="text-warm-500">full</span> {{ docStore.lowerResult.full_hash }}</span>
          </div>
          <pre class="font-mono text-[11.5px] bg-warm-50 dark:bg-warm-950 rounded-md p-2 whitespace-pre">{{ docStore.lowerResult.lowered }}</pre>
        </template>
        <div v-else class="text-coral">Lowering stopped; see Problems.</div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from "vue"

import { formatLiteral } from "@/graph/literal"
import { useDocumentStore } from "@/stores/document"
import { useUiStore } from "@/stores/ui"

const docStore = useDocumentStore()
const ui = useUiStore()

const TABS = [
  { id: "problems", label: "Problems", icon: "i-carbon-warning-alt" },
  { id: "run", label: "Run", icon: "i-carbon-play" },
  { id: "lowered", label: "Lowered", icon: "i-carbon-flow-stream" },
]

const passSummary = computed(() => {
  const on = docStore.passesOn.length
  if (on === docStore.passCatalog.length) return "all passes"
  return on ? `${on} of ${docStore.passCatalog.length} passes` : "as written"
})
</script>

<style>
.kir-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  height: 1.6rem;
  padding: 0 0.6rem;
  border-radius: 0.375rem;
  font-size: 11.5px;
  color: var(--color-text-muted);
}
.kir-tab:hover {
  background: var(--color-surface-alt);
}
.kir-tab--on {
  color: var(--kt-color-iolite);
  background: rgb(90 79 207 / 0.08);
}
.kir-pass {
  height: 1.35rem;
  padding: 0 0.5rem;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  border: 1px solid var(--color-border);
  color: var(--color-text-muted);
}
.kir-pass--on {
  border-color: var(--kt-color-iolite);
  color: var(--kt-color-iolite);
  background: rgb(90 79 207 / 0.08);
}
.kir-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.1rem;
  height: 1.1rem;
  padding: 0 0.25rem;
  border-radius: 999px;
  font-size: 10px;
  color: #fff;
}
</style>
