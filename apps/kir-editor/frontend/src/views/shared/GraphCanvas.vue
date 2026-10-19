<template>
  <div ref="root" class="kir-surface relative h-full w-full" :class="surfaceClass" tabindex="0" @keydown="onKey" @dragover.prevent="onDragOver" @drop.prevent="onDrop">
    <VueFlow :id="flowId" :nodes="flow.nodes" :edges="flow.edges" :node-types="nodeTypes" :edge-types="edgeTypes" :is-valid-connection="isValidConnection" :delete-key-code="null" :min-zoom="0.08" :max-zoom="2.5" :connect-on-click="false" @connect="onConnect" @node-click="onNodeClick" @node-drag-stop="onDragStop" @pane-click="docStore.selectedId = null">
      <Background :gap="20" :size="1.2" pattern-color="var(--kir-grid)" />
      <Controls :show-interactive="false" position="bottom-left">
        <ControlButton title="Lay out again" @click="relayoutNow"><span class="i-carbon-chart-network text-[13px]" /></ControlButton>
        <ControlButton :title="showMap ? 'Hide the minimap' : 'Show the minimap'" @click="mapChoice = !showMap"><span class="i-carbon-map text-[13px]" /></ControlButton>
      </Controls>
      <MiniMap v-if="showMap" pannable zoomable :width="150" :height="100" mask-color="rgb(160 154 146 / 0.18)" />
    </VueFlow>
    <div class="absolute top-2 left-2 flex items-center gap-2 pointer-events-none">
      <span v-if="layingOut" class="chip-iolite"><span class="i-carbon-circle-dash animate-spin mr-1 text-[10px]" />layout</span>
      <span v-if="layoutError" class="chip-coral pointer-events-auto" :title="layoutError">layout failed: {{ layoutError.slice(0, 120) }}</span>
      <span v-if="!flow.nodes.length" class="text-xs text-warm-500">Empty graph: drag nodes in from the palette.</span>
    </div>
    <slot />
  </div>
</template>

<script setup>
import { computed, markRaw, nextTick, ref, toRaw, watch } from "vue"
import { VueFlow, useVueFlow } from "@vue-flow/core"
import { Background } from "@vue-flow/background"
import { ControlButton, Controls } from "@vue-flow/controls"
import { MiniMap } from "@vue-flow/minimap"

import { isValidConnection } from "@/graph/edit"
import { useDocumentStore } from "@/stores/document"

/**
 * A graph canvas shared by the node and flowchart views. The view supplies
 * how to lay a graph out (`relayout`) and how to turn graph + layout into
 * Vue Flow nodes and edges (`build`); the canvas owns editing: wiring,
 * selection, moves, Delete, and drops from the palette.
 */
const props = defineProps({
  flowId: { type: String, required: true },
  layoutKey: { type: String, required: true },
  /** Changes when the view needs a new layout (another style, new structure). */
  layoutToken: { type: String, default: "" },
  relayout: { type: Function, required: true },
  build: { type: Function, required: true },
  nodeTypes: { type: Object, required: true },
  edgeTypes: { type: Object, required: true },
  surfaceClass: { type: String, default: "" },
  /** `(flowPosition) -> node id` to insert a dropped node after, or null. */
  dropAfter: { type: Function, default: null },
  /** Default minimap visibility. */
  minimap: { type: Boolean, default: false },
})

const DRAG_MIME = "application/x-kir-node"
const docStore = useDocumentStore()
const root = ref(null)
const layingOut = ref(false)
const layoutError = ref(null)
const mapChoice = ref(null)
const showMap = computed(() => mapChoice.value ?? props.minimap)

const nodeTypes = Object.fromEntries(Object.entries(props.nodeTypes).map(([k, v]) => [k, markRaw(v)]))
const edgeTypes = Object.fromEntries(Object.entries(props.edgeTypes).map(([k, v]) => [k, markRaw(v)]))

const { fitView, screenToFlowCoordinate, getSelectedNodes, getSelectedEdges, viewport, dimensions } =
  useVueFlow(props.flowId)

const layout = computed(() => docStore.layouts[props.layoutKey] || null)

const flow = computed(() => {
  void docStore.version
  // Selection is read untracked: Vue Flow owns it while the user clicks around.
  const selectedId = toRaw(docStore.$state).selectedId
  return props.build(docStore.graph, layout.value, selectedId)
})

let layoutRun = 0
async function ensureLayout(force = false) {
  const key = props.layoutKey
  const current = docStore.layouts[key]
  if (!force && current && current.token === props.layoutToken) return
  const run = ++layoutRun
  layingOut.value = true
  try {
    const next = await props.relayout(docStore.graph)
    if (run !== layoutRun || key !== props.layoutKey) return
    next.token = props.layoutToken
    docStore.setLayout(key, next)
    layoutError.value = null
    await nextTick()
    setTimeout(() => fitView({ padding: 0.1, maxZoom: 1.1 }), 30)
  } catch (e) {
    layoutError.value = String(e?.message || e)
  } finally {
    if (run === layoutRun) layingOut.value = false
  }
}

watch(() => [props.layoutKey, props.layoutToken, docStore.epoch, !!layout.value], () => ensureLayout(), { immediate: true })

function relayoutNow() {
  ensureLayout(true)
}

function onConnect(c) {
  if (!c.source.includes("__") && !c.target.includes("__")) docStore.connect(c)
}

function onNodeClick({ node }) {
  if (node.type !== "region" && !node.id.includes("__")) docStore.selectedId = node.id
}

function onDragStop({ nodes }) {
  for (const n of nodes) docStore.moveNode(props.layoutKey, n.id, n.position)
}

function onKey(event) {
  if (event.key !== "Delete" && event.key !== "Backspace") return
  if (event.target?.closest?.("input, textarea, select, [contenteditable='true']")) return
  // Regions and view-only elements (ids with `__`, like a flowchart's Start) stand for no statement.
  const nodes = getSelectedNodes.value.filter((n) => n.type !== "region" && !n.id.includes("__")).map((n) => n.id)
  const edges = getSelectedEdges.value.map((e) => e.id).filter((id) => !id.includes("__"))
  if (nodes.length) docStore.removeNodes(nodes, props.layoutKey)
  else if (edges.length) docStore.removeEdges(edges)
  event.preventDefault()
}

function onDragOver(event) {
  event.dataTransfer.dropEffect = "copy"
}

function place(spec, pos) {
  const after = props.dropAfter ? props.dropAfter(pos) : null
  docStore.addNode(spec, pos, props.layoutKey, after)
}

function onDrop(event) {
  const raw = event.dataTransfer.getData(DRAG_MIME)
  if (!raw) return
  const pos = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  place(JSON.parse(raw), { x: pos.x - 40, y: pos.y - 14 })
  root.value?.focus()
}

/** Add a node at the middle of the view (palette click). */
function addAtCenter(spec) {
  const { x, y, zoom } = viewport.value
  const { width, height } = dimensions.value
  const jitter = (Math.random() - 0.5) * 60
  place(spec, { x: (width / 2 - x) / zoom - 60 + jitter, y: (height / 2 - y) / zoom - 20 + jitter })
}

// The dev server lets the browser smoke test (tests/e2e) frame nodes before it drags between them.
if (import.meta.env.DEV && window.__kir) (window.__kir.flows ||= {})[props.flowId] = fitView

defineExpose({ addAtCenter, fit: () => fitView({ padding: 0.1, maxZoom: 1.1 }), fitView })
</script>
