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
      :editable="editable"
      :memory="memoryOf(flowId)"
      :relayout-key="relayoutKey"
      :is-valid-connection="isValidConnection"
      :drop-types="dropTypes"
      @select="select"
      @open="(s) => emit('open', s)"
      @hover="(s) => emit('hover', s)"
      @layout="(s) => emit('layout', s)"
      @connect="(c) => emit('connect', c)"
      @delete="(d) => emit('delete', d)"
      @drop="(d) => emit('drop', d)"
      @move="(m) => emit('move', m)"
    />
    <BlocksView v-else-if="view === 'blocks'" :model="model" />
    <SequenceView v-else-if="view === 'sequence'" :model="model" />
    <slot />
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue"

import { createMemory } from "../layout/place.js"
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
 *   while an overlay is given, else 0;
 * - `revision`: any value that changes when `doc` was changed in place (the
 *   model is rebuilt from it then; a new `doc` object rebuilds it too).
 *
 * Editing (`editable`; graph views): elements drag, pins take new wires,
 * unwired inputs and literals get input boxes, merges a free slot. The
 * document is never changed here: every edit comes out as an event for the
 * host to apply. A graph change keeps every element where it was drawn
 * (layout/place.js, remembered per view and graph for this component's life);
 * a new `relayoutKey` lays out afresh. `isValidConnection(c)` vets a wire
 * being drawn; drops whose data has one of `dropTypes` are passed on.
 *
 * Emits `select` (`{type: node|region|edge, id, key, node?}` or null), `open` (a node or
 * region double-clicked, as `select` gives it: a host opens a called `@def`'s graph), `hover`,
 * `layout` (`{ms, cached, nodes, regions, edges, layout}`), `update:collapsed`;
 * while editing `connect` (`{source, sourceHandle, target, targetHandle}`),
 * `delete` (`{nodes: [id], edges: [edge key]}`), `drop` (`{event, position,
 * region}`: page position, innermost region id there), `edit` (`{id, port,
 * value}`: a literal typed; `undefined` clears it) and `move` (`[{id,
 * position}]`).
 *
 * The default slot is drawn over the view, inside the theme (a legend, a
 * toolbar). Exposed: `fit(opts?)` (Vue Flow `fitView` options, e.g. `{nodes:
 * [ids]}`), `relayout()`, `place(id, position)` (where a node about
 * to be added is drawn), `center()` (the page point mid-view) and
 * `positions()` (node id -> drawn position).
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
  revision: { default: null },
  editable: { type: Boolean, default: false },
  relayoutKey: { default: null },
  isValidConnection: { type: Function, default: null },
  dropTypes: { type: Array, default: () => [] },
})
const emit = defineEmits(["select", "open", "hover", "layout", "update:collapsed", "connect", "delete", "drop", "edit", "move"])

const state = createGraphState()
provideGraphState(state)
const flow = ref(null)

// What an editable view remembers of each view and graph it drew
const memories = new Map()
function memoryOf(id) {
  if (!props.editable) return null
  if (!memories.has(id)) memories.set(id, createMemory())
  return memories.get(id)
}

// The model or the reason there is none, in one value: the template reads `problem` before it
// passes `model`, so both must come from the same evaluation
const built = computed(() => {
  void props.revision
  try {
    return { model: graphModel(props.doc, props.graph), problem: null }
  } catch (e) {
    return { model: null, problem: String(e?.message || e) }
  }
})
const model = computed(() => built.value.model)
const problem = computed(() => built.value.problem)
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
state.open = (s) => emit("open", s)
state.edit = (e) => emit("edit", e)

function select(s) {
  if (props.selected === undefined || props.selected === null) state.selected.value = s?.key ?? null
  emit("select", s)
}

watch(() => props.selected, (k) => (state.selected.value = k), { immediate: true })
watch(() => props.wireStyle, (w) => (state.wireStyle.value = w), { immediate: true })
watch(() => props.editable, (on) => (state.editable.value = on), { immediate: true })
watch(() => props.overlay, (o) => syncMap(state.nodes, o), { immediate: true })
watch(() => props.edgeOverlay, (o) => syncMap(state.edges, o), { immediate: true })
watch(() => props.regionOverlay, (o) => syncMap(state.regions, o), { immediate: true })

defineExpose({
  fit: (opts) => flow.value?.fit(opts),
  relayout: () => flow.value?.relayout(),
  place: (id, position) => flow.value?.place(id, position),
  center: () => flow.value?.center() ?? { x: 0, y: 0 },
  positions: () => flow.value?.positions() ?? new Map(),
})
</script>

<script>
let instances = 0
</script>
