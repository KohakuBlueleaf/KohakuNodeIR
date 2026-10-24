<template>
  <div class="relative h-full w-full">
    <KirGraph
      ref="graph"
      :doc="doc"
      :graph="docStore.graphName"
      :view="view"
      :revision="docStore.version"
      :relayout-key="docStore.epoch"
      :selected="docStore.selectedId"
      :minimap="minimap"
      editable
      :drop-types="[DRAG_MIME]"
      :is-valid-connection="isValidConnection"
      @select="onSelect"
      @connect="(c) => docStore.connect(c)"
      @delete="onDelete"
      @drop="onDrop"
      @edit="({ id, port, value }) => docStore.setInputValue(id, port, value)"
      @move="onMove"
      @layout="notePositions"
    >
      <slot />
    </KirGraph>
  </div>
</template>

<script setup>
import { computed, ref, toRaw } from "vue"
import { KirGraph } from "@kohaku/kir-graph"

import { isValidConnection as validConnection } from "@/graph/edit"
import { useDocumentStore } from "@/stores/document"

/**
 * The editor's graph canvas: a kir-graph view (`view`) of the current graph,
 * editable. The library draws and lays out; every edit it reports (a wire, a
 * delete, a drop from the palette, a literal typed, a move) is applied to
 * the document here, and the document redraws it.
 *
 * `dropAfter(region)`: the statement a node dropped into `region` (a region
 * id, or null outside every region) goes after on the control chain, or
 * null; `stampsMeta`: this canvas's positions are the ones `@meta pos`
 * records.
 */
const props = defineProps({
  name: { type: String, required: true },
  view: { type: String, required: true },
  dropAfter: { type: Function, default: null },
  minimap: { type: Boolean, default: false },
  stampsMeta: { type: Boolean, default: false },
})

const DRAG_MIME = "application/x-kir-node"
const docStore = useDocumentStore()
const graph = ref(null)

// The library reads the document as plain data; `revision` tells it when the document changed in place
const doc = computed(() => toRaw(docStore.doc))
const isValidConnection = (c) => validConnection(c, docStore.graph)

function onSelect(s) {
  docStore.selectedId = s?.type === "node" && docStore.graph.nodes.some((n) => n.id === s.id) ? s.id : null
}

function onDelete({ nodes, edges }) {
  if (nodes.length) docStore.removeNodes(nodes)
  else docStore.removeEdges(edges)
}

/** Add a node drawn at `position`; in a region it joins that region's statements when the view says where. */
function place(spec, position, region) {
  const after = props.dropAfter ? props.dropAfter(region) : null
  const node = docStore.addNode(spec, { after, region: props.dropAfter ? region : null })
  graph.value?.place(node.id, position)
}

function onDrop({ event, position, region }) {
  const raw = event.dataTransfer.getData(DRAG_MIME)
  if (raw) place(JSON.parse(raw), { x: position.x - 40, y: position.y - 14 }, region)
}

function onMove(moved) {
  for (const m of moved) docStore.moveNode(m.id, m.position)
  notePositions()
}

function notePositions() {
  if (props.stampsMeta && graph.value) docStore.notePositions(docStore.graphName, graph.value.positions())
}

/** Add a node at the middle of the view (palette click). */
function addAtCenter(spec) {
  const c = graph.value?.center() ?? { x: 0, y: 0 }
  const jitter = (Math.random() - 0.5) * 60
  place(spec, { x: c.x - 60 + jitter, y: c.y - 20 + jitter }, null)
}

const fit = (opts) => graph.value?.fit(opts)
const relayout = () => graph.value?.relayout()

// The dev server lets the browser smoke test (tests/e2e) frame nodes before it drags between them
if (import.meta.env.DEV && window.__kir) (window.__kir.flows ||= {})[props.name] = fit

defineExpose({ addAtCenter, fit, relayout })
</script>
