<template>
  <div ref="root" class="kir-surface relative h-full w-full" tabindex="0" @keydown="onKey" @dragover.prevent="onDragOver" @drop.prevent="onDrop">
    <VueFlow :id="FLOW_ID" :nodes="flow.nodes" :edges="flow.edges" :node-types="nodeTypes" :edge-types="edgeTypes" :is-valid-connection="isValidConnection" :delete-key-code="null" :min-zoom="0.1" :max-zoom="2.5" :default-edge-options="{ type: 'kir' }" :connect-on-click="false" @connect="onConnect" @node-click="onNodeClick" @node-drag-stop="onDragStop" @pane-click="onPaneClick">
      <Background :gap="20" :size="1.2" pattern-color="var(--kir-grid)" />
      <Controls :show-interactive="false" position="bottom-left">
        <ControlButton :title="showMap ? 'Hide the minimap' : 'Show the minimap'" @click="mapChoice = !showMap"><span class="i-carbon-map text-[13px]" /></ControlButton>
      </Controls>
      <MiniMap v-if="showMap" pannable zoomable :width="150" :height="100" :node-color="miniColor" mask-color="rgb(160 154 146 / 0.18)" />
    </VueFlow>

    <div class="absolute top-3 left-3 flex items-center gap-2 pointer-events-none">
      <span v-if="docStore.layingOut" class="chip-iolite"><span class="i-carbon-circle-dash animate-spin mr-1 text-[10px]" />layout</span>
      <span v-if="docStore.layoutError" class="chip-coral pointer-events-auto" :title="docStore.layoutError">layout failed: {{ docStore.layoutError.slice(0, 120) }}</span>
      <span v-if="isEmpty" class="text-xs text-warm-500">Empty graph: drag nodes in from the palette.</span>
    </div>
    <GraphLegend class="absolute top-3 right-3" />
  </div>
</template>

<script setup>
import { computed, markRaw, nextTick, ref, toRaw, watch } from "vue"
import { VueFlow, useVueFlow } from "@vue-flow/core"
import { Background } from "@vue-flow/background"
import { ControlButton, Controls } from "@vue-flow/controls"
import { MiniMap } from "@vue-flow/minimap"

import GraphLegend from "@/components/graph/GraphLegend.vue"
import KirEdge from "@/components/graph/edges/KirEdge.vue"
import FrameNode from "@/components/graph/nodes/FrameNode.vue"
import KirNode from "@/components/graph/nodes/KirNode.vue"
import { isValidConnection } from "@/graph/edit"
import { toFlow } from "@/graph/flow"
import { useDocumentStore } from "@/stores/document"
import { useUiStore } from "@/stores/ui"

const FLOW_ID = "kir-graph"
const DRAG_MIME = "application/x-kir-node"

const docStore = useDocumentStore()
const ui = useUiStore()
const root = ref(null)

// The minimap covers a corner of the canvas: shown by default only in the full-width graph view.
const mapChoice = ref(null)
const showMap = computed(() => mapChoice.value ?? ui.view === "graph")
const nodeTypes = { kir: markRaw(KirNode), frame: markRaw(FrameNode) }
const edgeTypes = { kir: markRaw(KirEdge) }

const { fitView, screenToFlowCoordinate, getSelectedNodes, getSelectedEdges, viewport, dimensions } = useVueFlow(FLOW_ID)

const flow = computed(() => {
  void docStore.version
  // Selection is read untracked: Vue Flow owns it while the user clicks around.
  const selectedId = toRaw(docStore.$state).selectedId
  return toFlow(docStore.graph, docStore.layout, { defNames: docStore.defNames }, selectedId)
})

const isEmpty = computed(() => flow.value.nodes.length === 0)

watch(
  () => docStore.layout,
  async (layout, old) => {
    if (!layout || layout === old) return
    await nextTick()
    setTimeout(() => fitView({ padding: 0.12, maxZoom: 1.1 }), 30)
  },
)

function onConnect(connection) {
  docStore.connect(connection)
}

function onNodeClick({ node }) {
  docStore.selectedId = node.id
}

function onPaneClick() {
  docStore.selectedId = null
}

function onDragStop({ nodes }) {
  for (const n of nodes) docStore.moveNode(n.id, n.position)
}

function onKey(event) {
  if (event.key !== "Delete" && event.key !== "Backspace") return
  const tag = event.target?.tagName
  if (tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable) return
  const nodes = getSelectedNodes.value.map((n) => n.id)
  const edges = getSelectedEdges.value.map((e) => e.id)
  if (nodes.length) docStore.removeNodes(nodes)
  else if (edges.length) docStore.removeEdges(edges)
  event.preventDefault()
}

function onDragOver(event) {
  event.dataTransfer.dropEffect = "copy"
}

function onDrop(event) {
  const raw = event.dataTransfer.getData(DRAG_MIME)
  if (!raw) return
  const spec = JSON.parse(raw)
  const pos = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  docStore.addNode(spec, { x: pos.x - 40, y: pos.y - 14 })
  root.value?.focus()
}

/** Add a node at the middle of the view (palette click). */
function addAtCenter(spec) {
  const { x, y, zoom } = viewport.value
  const { width, height } = dimensions.value
  const jitter = (Math.random() - 0.5) * 60
  docStore.addNode(spec, { x: (width / 2 - x) / zoom - 60 + jitter, y: (height / 2 - y) / zoom - 20 + jitter })
}

function miniColor(n) {
  if (n.type === "frame") return "rgb(76 153 137 / 0.25)"
  const kind = n.data?.node?.kind
  if (["branch", "switch", "merge", "parallel", "each"].includes(kind)) return "#5A4FCF"
  if (kind === "value") return "#D4920A"
  if (kind === "try") return "#D46B6B"
  return "#A09A92"
}

// The dev server lets the browser smoke test (tests/e2e) frame nodes before it drags between them.
if (import.meta.env.DEV && window.__kir) window.__kir.flow = { fitView }

defineExpose({ addAtCenter, fit: () => fitView({ padding: 0.12, maxZoom: 1.1 }) })
</script>
