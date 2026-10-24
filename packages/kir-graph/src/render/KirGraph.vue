<template>
  <div class="kg-root" :class="[themeClass, `kg-view--${view}`]">
    <div v-if="problem" class="kg-problem">{{ problem }}</div>
    <FlowView
      v-else-if="graphView"
      ref="flow"
      :key="flowId"
      :flow-id="flowId"
      :model="model"
      :view="graphView"
      :regions="regions"
      :collapsed="collapsedList"
      :options="layoutOptions"
      :minimap="minimap"
      @select="select"
      @hover="(s) => emit('hover', s)"
      @layout="(s) => emit('layout', s)"
    />
    <BlocksView v-else-if="view === 'blocks'" :model="model" />
    <SequenceView v-else-if="view === 'sequence'" :model="model" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue"

import { graphModel } from "../model/graph.js"
import { GRAPH_VIEWS } from "../views.js"
import FlowView from "./flow/FlowView.vue"
import { createGraphState, provideGraphState, syncMap } from "./overlay.js"
import BlocksView from "./statements/BlocksView.vue"
import SequenceView from "./statements/SequenceView.vue"

/**
 * A KIR program drawn in one of six views: `nodes` (cards, control wires),
 * `frames` (cards boxed by region, control as order), `dataflow` (data
 * only), `flowchart` (ROBO Pro elements), `blocks` (Scratch) and `sequence`
 * (EV3). Every view reads the same `.kirgraph` (version 3), the same overlay
 * (render/overlay.js) and the same collapsed regions.
 *
 * Props:
 * - `doc`: the `.kirgraph` document; `graph`: which of its graphs (`main`);
 * - `regions`: draw region boxes (graph views);
 * - `collapsed` (v-model): ids of collapsed regions;
 * - `overlay`, `edgeOverlay`, `regionOverlay`: Map or object of entries;
 * - `selected`: the selected node key (path, else id) or region id;
 * - `theme`: "inherit" (dark under `html.dark`), "light" or "dark";
 * - `wireStyle`: "rail" (control a hollow double line, data a thin one) or
 *   "plain" (both solid, told apart by colour and width);
 * - `layout`: layout options (layout/build.js `planLayout`, `layoutView`), e.g.
 *   `{layering, placement, aspect, wrap, compact, markRows}`; `markRows` is 2
 *   while an overlay is given, else 0.
 *
 * Emits `select` (`{type: node|region|edge, id, key, node?}` or null), `hover`,
 * `layout` (`{ms, cached, nodes, regions, edges, layout}`), `update:collapsed`.
 */
defineOptions({ name: "KirGraph" })
const props = defineProps({
  doc: { type: Object, required: true },
  graph: { type: String, default: "main" },
  view: { type: String, default: "nodes" },
  regions: { type: Boolean, default: true },
  collapsed: { type: Array, default: null },
  overlay: { type: [Map, Object], default: null },
  edgeOverlay: { type: [Map, Object], default: null },
  regionOverlay: { type: [Map, Object], default: null },
  selected: { type: String, default: null },
  theme: { type: String, default: "inherit" },
  wireStyle: { type: String, default: "rail" },
  layout: { type: Object, default: () => ({}) },
  minimap: { type: Boolean, default: true },
})
const emit = defineEmits(["select", "hover", "layout", "update:collapsed"])

const state = createGraphState()
provideGraphState(state)
const flow = ref(null)

const problem = ref(null)
const model = computed(() => {
  try {
    problem.value = null
    return graphModel(props.doc, props.graph)
  } catch (e) {
    problem.value = String(e?.message || e)
    return null
  }
})
const graphView = computed(() => GRAPH_VIEWS[props.view] || null)
// With an overlay, two rows of marks are kept clear over every element
const hasOverlay = computed(() => !!(props.overlay || props.edgeOverlay || props.regionOverlay))
const layoutOptions = computed(() => ({ markRows: hasOverlay.value ? 2 : 0, ...props.layout }))
const uid = ++instances
const flowId = computed(() => `kir-graph-${uid}-${props.view}-${props.graph}`)
const themeClass = computed(() => (props.theme === "dark" ? "kg-dark" : props.theme === "light" ? "kg-light" : ""))

// Collapsed regions: the v-model when given, else kept here
const own = ref([])
const collapsedList = computed(() => props.collapsed ?? own.value)
watch(collapsedList, (list) => (state.collapsed.value = new Set(list)), { immediate: true })
state.toggle = (rid) => {
  const set = new Set(collapsedList.value)
  if (set.has(rid)) set.delete(rid)
  else set.add(rid)
  flow.value?.anchorRegion(rid)
  const next = [...set]
  own.value = next
  emit("update:collapsed", next)
}
state.select = (s) => select(s)

function select(s) {
  if (props.selected === undefined || props.selected === null) state.selected.value = s?.key ?? null
  emit("select", s)
}

watch(() => props.selected, (k) => (state.selected.value = k), { immediate: true })
watch(() => props.wireStyle, (w) => (state.wireStyle.value = w), { immediate: true })
watch(() => props.overlay, (o) => syncMap(state.nodes, o), { immediate: true })
watch(() => props.edgeOverlay, (o) => syncMap(state.edges, o), { immediate: true })
watch(() => props.regionOverlay, (o) => syncMap(state.regions, o), { immediate: true })

defineExpose({ fit: () => flow.value?.fit() })
</script>

<script>
let instances = 0
</script>
