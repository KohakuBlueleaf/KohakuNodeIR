<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="kir-viewbar">
      <span class="kir-viewbar__title"><span class="i-carbon-flow-stream" />Flowchart</span>
      <span class="text-[10.5px] text-warm-500">program flow top → bottom from Start · variables are VAR elements beside the flow</span>
    </div>
    <div class="flex-1 min-h-0">
      <GraphCanvas ref="canvas" flow-id="kir-flowchart" :layout-key="docStore.layoutKey('flowchart')" :layout-token="docStore.dataStyle" :relayout="relayout" :build="build" :node-types="NODE_TYPES" :edge-types="EDGE_TYPES" :minimap="ui.view !== 'split'" surface-class="robo-surface" />
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue"

import { toFlow } from "@/graph/flow"
import { layoutGraph } from "@/graph/layout"
import { membership } from "@/graph/ports"
import { roboGeometry } from "@/graph/styles/robo"
import { useDocumentStore } from "@/stores/document"
import { useUiStore } from "@/stores/ui"
import RoboNode from "@/views/flowchart/RoboNode.vue"
import GraphCanvas from "@/views/shared/GraphCanvas.vue"
import GroupNode from "@/views/shared/GroupNode.vue"
import WireEdge from "@/views/shared/WireEdge.vue"

const NODE_TYPES = { robo: RoboNode, group: GroupNode }
const EDGE_TYPES = { wire: WireEdge }
// ROBO Pro: blue program flow, orange data and variable lines.
const FLOW_BLUE = "#1F5FD0"
const DATA_ORANGE = "#E08A10"

const docStore = useDocumentStore()
const ui = useUiStore()
const canvas = ref(null)

const geometry = (n) => roboGeometry(n, { defNames: docStore.defNames })

/**
 * The graph with a Start element before the first statement and an End
 * element after every way out of the program. They stand for no statement
 * (their ids contain `__`, which programs may not use) and are never sent
 * back as text.
 */
function withTerminals(graph) {
  if (!graph || graph.name !== "main") return graph
  const memberOf = membership(graph)
  const ctrl = graph.edges.filter((e) => e.kind === "ctrl")
  const entered = new Set(ctrl.map((e) => e.to.node))
  const leaving = new Set(ctrl.map((e) => `${e.from.node}|${e.from.port}`))
  const chain = graph.nodes.filter((n) => !memberOf.has(n.id) && (n.ctrl_in || []).includes("in"))
  const first = chain.find((n) => !entered.has(n.id))
  const exits = []
  for (const n of graph.nodes) {
    if (memberOf.has(n.id)) continue
    for (const p of n.ctrl_out || []) if (!leaving.has(`${n.id}|${p}`)) exits.push({ node: n.id, port: p })
  }
  const nodes = [...graph.nodes, { id: "__start", kind: "start" }]
  const edges = [...graph.edges]
  if (first) edges.push({ kind: "ctrl", from: { node: "__start", port: "out" }, to: { node: first.id, port: "in" } })
  if (exits.length) {
    nodes.push({ id: "__end", kind: "end" })
    for (const x of exits) edges.push({ kind: "ctrl", from: x, to: { node: "__end", port: "in" } })
  }
  return { ...graph, nodes, edges }
}

function relayout(graph) {
  return layoutGraph(withTerminals(graph), { geometry, direction: "DOWN", frameSides: ["NORTH", "SOUTH"] })
}

function build(graph, layout, selectedId) {
  return toFlow(withTerminals(graph), layout, {
    geometry,
    nodeType: "robo",
    showCtrl: true,
    frameSides: ["NORTH", "SOUTH"],
    selectedId,
    ctrlColor: FLOW_BLUE,
    dataColor: () => DATA_ORANGE,
    arrows: true,
    extra: { exec: true },
  })
}

defineExpose({ addAtCenter: (spec) => canvas.value?.addAtCenter(spec) })
</script>
