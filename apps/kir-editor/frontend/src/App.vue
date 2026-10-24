<template>
  <div class="kg-theme h-full flex flex-col text-warm-800 dark:text-warm-100">
    <AppHeader />
    <div class="flex-1 flex min-h-0">
      <PalettePanel class="w-56 shrink-0" @add="addNode" />
      <main class="flex-1 flex flex-col min-w-0 min-h-0">
        <div class="flex-1 flex min-h-0">
          <template v-for="(v, i) in ui.shown" :key="v">
            <div v-if="i > 0" class="w-px bg-warm-200 dark:bg-warm-800 shrink-0" />
            <div class="flex-1 min-w-0 min-h-0" :data-view="v">
              <component :is="VIEW_COMPONENTS[v]" :ref="(el) => (views[v] = el)" />
            </div>
          </template>
        </div>
        <BottomPanel v-if="ui.bottomOpen" class="h-52 shrink-0" />
      </main>
      <InspectorPanel class="w-72 shrink-0" />
    </div>
    <StatusBar />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, watch } from "vue"

import AppHeader from "@/components/chrome/AppHeader.vue"
import StatusBar from "@/components/chrome/StatusBar.vue"
import BottomPanel from "@/components/panels/BottomPanel.vue"
import InspectorPanel from "@/components/panels/InspectorPanel.vue"
import PalettePanel from "@/components/panels/PalettePanel.vue"
import { SAMPLES } from "@/samples"
import { useDocumentStore } from "@/stores/document"
import { useLibraryStore } from "@/stores/library"
import { useUiStore } from "@/stores/ui"
import BlocksView from "@/views/blocks/BlocksView.vue"
import FlowchartView from "@/views/flowchart/FlowchartView.vue"
import NodesView from "@/views/nodes/NodesView.vue"
import SequenceView from "@/views/sequence/SequenceView.vue"
import TextView from "@/views/text/TextView.vue"

const VIEW_COMPONENTS = {
  nodes: NodesView,
  flowchart: FlowchartView,
  sequence: SequenceView,
  blocks: BlocksView,
  text: TextView,
}

const ui = useUiStore()
const docStore = useDocumentStore()
const lib = useLibraryStore()
const views = reactive({})

// The dev server exposes the stores to the browser smoke test (tests/e2e).
if (import.meta.env.DEV) window.__kir = { doc: docStore, lib, ui }

/** The flowchart draws variables as elements, so it asks for the variables style. */
const wantedData = () => (ui.shown.includes("flowchart") ? "variables" : ui.data)
watch(wantedData, (style) => docStore.setDataStyle(style))

/** Palette click: the first view on screen that can take a new statement adds it. */
function addNode(spec) {
  for (const v of ui.shown) {
    if (views[v]?.addAtCenter) {
      views[v].addAtCenter(spec)
      return
    }
  }
  ui.setView("nodes")
  setTimeout(() => views.nodes?.addAtCenter(spec), 50)
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
onBeforeUnmount(() => window.removeEventListener("keydown", onKey))

// URL parameters pick the start state (stores/ui.js lists them), plus ?sample=<id>&graph=<@def name>.
onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  ui.initTheme(params.get("theme"))
  ui.fromUrl(params)
  docStore.dataStyle = wantedData()
  await Promise.all([lib.load(), docStore.loadPasses()])
  const sample = SAMPLES.find((s) => s.id === params.get("sample")) || SAMPLES[0]
  await docStore.loadText(sample.text, `${sample.id}.kir`)
  if (params.get("graph") && docStore.graphNames.includes(params.get("graph")))
    await docStore.selectGraph(params.get("graph"))
})
</script>
