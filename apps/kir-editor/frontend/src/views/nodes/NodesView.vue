<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="kir-viewbar">
      <span class="kir-viewbar__title"><span class="i-carbon-flow" />Nodes</span>
      <KnobGroup label="data" knob="data" :options="KNOBS.data" />
      <KnobGroup label="control" knob="control" :options="KNOBS.control" />
      <span v-if="ui.control === 'auto'" class="text-[10.5px] text-warm-500">→ {{ mode === "none" ? "no control" : mode }}</span>
      <span class="flex-1" />
      <span v-if="mode === 'frames'" class="text-[10.5px] text-warm-500 hidden xl:inline">drop a node into a region to append it there</span>
    </div>
    <div class="flex-1 min-h-0">
      <GraphCanvas ref="canvas" flow-id="kir-nodes" :layout-key="docStore.layoutKey('nodes')" :layout-token="token" :relayout="relayout" :build="build" :node-types="NODE_TYPES" :edge-types="EDGE_TYPES" :drop-after="dropAfter" :minimap="ui.view !== 'split'" surface-class="kir-surface--nodes">
        <GraphLegend class="absolute top-2 right-2" />
      </GraphCanvas>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue"

import { framesLayout } from "@/graph/frames"
import { toFlow } from "@/graph/flow"
import { layoutGraph } from "@/graph/layout"
import { cardGeometry } from "@/graph/styles/card"
import { useDocumentStore } from "@/stores/document"
import { KNOBS, useUiStore } from "@/stores/ui"
import CardNode from "@/views/nodes/CardNode.vue"
import RegionNode from "@/views/nodes/RegionNode.vue"
import GraphCanvas from "@/views/shared/GraphCanvas.vue"
import GraphLegend from "@/views/shared/GraphLegend.vue"
import GroupNode from "@/views/shared/GroupNode.vue"
import KnobGroup from "@/views/shared/KnobGroup.vue"
import WireEdge from "@/views/shared/WireEdge.vue"

const NODE_TYPES = { card: CardNode, region: RegionNode, group: GroupNode }
const EDGE_TYPES = { wire: WireEdge }
const CONTROL_KINDS = new Set(["branch", "switch", "each", "parallel", "try", "merge"])

const docStore = useDocumentStore()
const ui = useUiStore()
const canvas = ref(null)

/** The control style in effect: auto is frames when the graph has control statements, else none. */
const mode = computed(() => {
  if (ui.control !== "auto") return ui.control
  return docStore.graph?.nodes.some((n) => CONTROL_KINDS.has(n.kind)) ? "frames" : "none"
})

// Frames follow the program's structure, so they are laid out again whenever it changes.
const structureSerial = ref(0)
watch(() => docStore.structure, () => structureSerial.value++)

const token = computed(
  () => `${mode.value}|${docStore.dataStyle}${mode.value === "frames" ? `|${structureSerial.value}` : ""}`,
)

const geometry = (n) => cardGeometry(n, { defNames: docStore.defNames, exec: mode.value === "exec" })

async function relayout(graph) {
  if (mode.value === "frames") return framesLayout(graph, docStore.structure?.[docStore.graphName] || [], geometry)
  return layoutGraph(graph, { geometry, direction: "RIGHT", frameSides: ["WEST", "EAST"] })
}

function build(graph, layout, selectedId) {
  return toFlow(graph, layout, {
    geometry,
    nodeType: "card",
    showCtrl: mode.value === "exec",
    frameSides: ["WEST", "EAST"],
    hidden: layout?.hidden,
    regions: mode.value === "frames" ? layout?.regions : [],
    selectedId,
    extra: { exec: mode.value === "exec" },
  })
}

/** In frames style a dropped node joins the innermost region under it (else the main sequence). */
function dropAfter(pos) {
  if (mode.value !== "frames") return null
  const layout = docStore.layouts[docStore.layoutKey("nodes")]
  if (!layout) return null
  const hits = (layout.regions || []).filter(
    (r) => pos.x >= r.x && pos.x <= r.x + r.w && pos.y >= r.y && pos.y <= r.y + r.h && r.last,
  )
  hits.sort((a, b) => b.depth - a.depth)
  return hits[0]?.last || layout.last || null
}

defineExpose({ addAtCenter: (spec) => canvas.value?.addAtCenter(spec) })
</script>
