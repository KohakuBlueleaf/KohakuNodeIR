<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="kir-viewbar">
      <span class="kir-viewbar__title"><span class="i-carbon-flow-stream" />Flowchart</span>
      <span class="text-[10.5px] text-warm-500">program flow top → bottom from Start · variables are VAR elements beside the flow</span>
      <span class="flex-1" />
      <button class="btn-icon" title="Lay out again" @click="canvas?.relayout()"><span class="i-carbon-chart-network text-[13px]" /></button>
    </div>
    <div class="flex-1 min-h-0">
      <GraphCanvas ref="canvas" name="kir-flowchart" view="flowchart" :minimap="ui.view !== 'split'" />
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue"

import { useUiStore } from "@/stores/ui"
import GraphCanvas from "@/views/shared/GraphCanvas.vue"

/** The flowchart (ROBO Pro style) of the current graph: kir-graph's flowchart view, editable. */
const ui = useUiStore()
const canvas = ref(null)

defineExpose({ addAtCenter: (spec) => canvas.value?.addAtCenter(spec) })
</script>
