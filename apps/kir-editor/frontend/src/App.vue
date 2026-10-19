<template>
  <div class="h-full flex flex-col text-warm-800 dark:text-warm-100">
    <AppHeader />
    <div class="flex-1 flex min-h-0">
      <PalettePanel class="w-56 shrink-0" @add="addNode" />
      <main class="flex-1 flex flex-col min-w-0 min-h-0">
        <div class="flex-1 flex min-h-0">
          <div v-if="showGraph" class="flex-1 min-w-0 relative">
            <GraphCanvas ref="canvas" />
          </div>
          <div v-if="ui.view === 'split'" class="w-px bg-warm-200 dark:bg-warm-800" />
          <div v-if="showText" class="min-w-0" :class="ui.view === 'split' ? 'w-[42%]' : 'flex-1'">
            <CodeEditor />
          </div>
          <div v-if="ui.view === 'blocks'" class="flex-1 min-w-0">
            <BlocksView />
          </div>
        </div>
        <BottomPanel v-if="ui.bottomOpen" class="h-52 shrink-0" />
      </main>
      <InspectorPanel class="w-72 shrink-0" />
    </div>
    <StatusBar />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import BlocksView from "@/components/blocks/BlocksView.vue"
import AppHeader from "@/components/chrome/AppHeader.vue"
import StatusBar from "@/components/chrome/StatusBar.vue"
import GraphCanvas from "@/components/graph/GraphCanvas.vue"
import BottomPanel from "@/components/panels/BottomPanel.vue"
import InspectorPanel from "@/components/panels/InspectorPanel.vue"
import PalettePanel from "@/components/panels/PalettePanel.vue"
import CodeEditor from "@/components/text/CodeEditor.vue"
import { SAMPLES } from "@/samples"
import { useDocumentStore } from "@/stores/document"
import { useLibraryStore } from "@/stores/library"
import { VIEWS, useUiStore } from "@/stores/ui"

const ui = useUiStore()
const docStore = useDocumentStore()
const lib = useLibraryStore()
const canvas = ref(null)

const showGraph = computed(() => ui.view === "graph" || ui.view === "split")
const showText = computed(() => ui.view === "text" || ui.view === "split")

function addNode(spec) {
  if (!showGraph.value) ui.setView("split")
  setTimeout(() => canvas.value?.addAtCenter(spec), 0)
}

/** Ctrl+Z undo, Ctrl+Shift+Z / Ctrl+Y redo, except where a text field has its own undo. */
function onKey(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return
  const t = event.target
  if (t?.closest?.("input, textarea, select, [contenteditable='true'], .cm-editor")) return
  const key = event.key.toLowerCase()
  if (key === "z" && !event.shiftKey) docStore.undo()
  else if ((key === "z" && event.shiftKey) || key === "y") docStore.redo()
  else return
  event.preventDefault()
}

onMounted(() => window.addEventListener("keydown", onKey))
// The dev server exposes the stores to the browser smoke test (tests/e2e).
if (import.meta.env.DEV) window.__kir = { doc: docStore, lib, ui }
onBeforeUnmount(() => window.removeEventListener("keydown", onKey))

// URL parameters pick the start state: ?sample=<id>&view=<graph|split|text|blocks>&graph=<@def name>&theme=<light|dark>
onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  ui.initTheme(params.get("theme"))
  if (VIEWS.some((v) => v.id === params.get("view"))) ui.setView(params.get("view"))
  await Promise.all([lib.load(), docStore.loadPasses()])
  const sample = SAMPLES.find((s) => s.id === params.get("sample")) || SAMPLES[0]
  await docStore.loadText(sample.text, `${sample.id}.kir`)
  if (params.get("graph") && docStore.graphNames.includes(params.get("graph")))
    await docStore.selectGraph(params.get("graph"))
})
</script>
