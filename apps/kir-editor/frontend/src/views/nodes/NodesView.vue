<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="kir-viewbar">
      <span class="kir-viewbar__title"><span class="i-carbon-flow" />Nodes</span>
      <KnobGroup label="data" knob="data" :options="KNOBS.data" />
      <KnobGroup label="control" knob="control" :options="KNOBS.control" />
      <span v-if="ui.control === 'auto'" class="text-[10.5px] text-warm-500">→ {{ view }}</span>
      <span class="flex-1" />
      <span v-if="view === 'frames'" class="text-[10.5px] text-warm-500 truncate min-w-0 hidden xl:inline">drop a node into a region to append it there</span>
      <button class="btn-icon" title="Lay out again" @click="canvas?.relayout()"><span class="i-carbon-chart-network text-[13px]" /></button>
    </div>
    <div class="flex-1 min-h-0">
      <GraphCanvas ref="canvas" name="kir-nodes" :view="view" :drop-after="view === 'frames' ? dropAfter : null" :minimap="ui.view !== 'split'" stamps-meta>
        <GraphLegend class="absolute top-2 right-2" />
      </GraphCanvas>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue"

import { lastStatement } from "@/graph/edit"
import { useDocumentStore } from "@/stores/document"
import { KNOBS, useUiStore } from "@/stores/ui"
import GraphCanvas from "@/views/shared/GraphCanvas.vue"
import GraphLegend from "@/views/shared/GraphLegend.vue"
import KnobGroup from "@/views/shared/KnobGroup.vue"

const CONTROL_KINDS = new Set(["branch", "switch", "each", "collect", "parallel", "try", "merge"])

const docStore = useDocumentStore()
const ui = useUiStore()
const canvas = ref(null)

/**
 * The kir-graph view drawn: control wires (`exec` -> nodes), statements boxed
 * by region (`frames`), or with `auto` frames when the graph has control
 * statements, else data only (dataflow).
 */
const view = computed(() => {
  if (ui.control === "exec") return "nodes"
  if (ui.control === "frames") return "frames"
  return docStore.graph?.nodes.some((n) => CONTROL_KINDS.has(n.kind)) ? "frames" : "dataflow"
})

/** In frames a dropped node joins the end of the region under it, else of the main sequence. */
const dropAfter = (region) => lastStatement(docStore.graph, region)

defineExpose({ addAtCenter: (spec) => canvas.value?.addAtCenter(spec) })
</script>
