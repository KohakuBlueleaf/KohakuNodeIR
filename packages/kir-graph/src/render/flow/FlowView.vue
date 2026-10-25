<template>
  <div ref="root" class="kg-flow" :class="[`kg-lod--${lod}`, `kg-palette--${view.palette || 'gem'}`, { 'kg-flow--editable': editable }]" :tabindex="editable ? 0 : undefined" @keydown="onKey" @dragover="onDragOver" @drop="onDrop">
    <svg class="kg-defs" width="0" height="0" aria-hidden="true">
      <defs>
        <marker v-for="m in MARKERS" :id="m.id" :key="m.id" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" :style="{ fill: m.fill }" />
        </marker>
      </defs>
    </svg>
    <VueFlow
      :id="flowId"
      :nodes="nodes"
      :edges="edges"
      :node-types="NODE_TYPES"
      :edge-types="EDGE_TYPES"
      :nodes-draggable="editable"
      :nodes-connectable="editable"
      :elements-selectable="true"
      :connect-on-click="false"
      :only-render-visible-elements="nodes.length > VIRTUALIZE"
      :min-zoom="0.03"
      :max-zoom="2.5"
      :delete-key-code="null"
      @node-click="onNodeClick"
      @node-double-click="({ node }) => emit('open', selectionOf(node))"
      @edge-click="onEdgeClick"
      @node-mouse-enter="onEnter"
      @node-mouse-leave="onLeave"
      @node-drag-stop="onDragStop"
      @connect="onConnect"
      @pane-click="onPaneClick"
    >
      <Background :gap="22" :size="1.1" pattern-color="var(--kg-grid)" />
      <Controls :show-interactive="false" position="bottom-left" />
      <MiniMap v-if="minimap" pannable zoomable :width="160" :height="110" :node-color="miniColor" mask-color="var(--kg-minimap-mask)" />
    </VueFlow>
    <div v-if="busy || error" class="kg-flow__status">
      <span v-if="busy" class="kg-chip kg-chip--accent"><Icon name="circle-dash" class="kg-spin" />laying out {{ planned }} elements</span>
      <span v-if="error" class="kg-chip kg-chip--bad" :title="error">layout failed: {{ error.slice(0, 140) }}</span>
    </div>
  </div>
</template>

<script setup>
import { markRaw, nextTick, ref, shallowRef, watch } from "vue"
import { VueFlow, useVueFlow } from "@vue-flow/core"
import { Background } from "@vue-flow/background"
import { Controls } from "@vue-flow/controls"
import { MiniMap } from "@vue-flow/minimap"

import { fontsReady } from "../../geometry/measure.js"
import { nodeKey, regionNodes } from "../../model/graph.js"
import { isStatement } from "../../model/tree.js"
import { layoutView } from "../../layout/build.js"
import { forget, keepLayout, pinAt, placeLayout, remember } from "../../layout/place.js"
import Icon from "../Icon.vue"
import { dataName, useGraphState } from "../overlay.js"
import CardNode from "./CardNode.vue"
import CollapsedNode from "./CollapsedNode.vue"
import RegionNode from "./RegionNode.vue"
import RoboNode from "./RoboNode.vue"
import WireEdge from "./WireEdge.vue"

/**
 * A graph view of one graph: lays it out (layout/build.js) whenever the graph,
 * the view, region drawing or the collapsed set changes, and draws the result.
 * Overlay and selection changes never lay out again or rebuild elements.
 *
 * Editable (`editable`, with a `memory` from layout/place.js): elements drag,
 * pins take new wires, Delete removes the selection, and drops of
 * `dropTypes` are passed on; all of these come out as events and change
 * nothing here. A graph change keeps every element where it is
 * (`keepLayout`); a new `relayoutKey`, view, region drawing or option lays out
 * afresh.
 */
const props = defineProps({
  flowId: { type: String, required: true },
  model: { type: Object, required: true },
  view: { type: Object, required: true },
  regions: { type: Boolean, default: true },
  collapsed: { type: Array, default: () => [] },
  options: { type: Object, default: () => ({}) },
  minimap: { type: Boolean, default: true },
  lodFar: { type: Number, default: 0.22 },
  lodMid: { type: Number, default: 0.5 },
  editable: { type: Boolean, default: false },
  memory: { type: Object, default: null },
  relayoutKey: { default: null },
  isValidConnection: { type: Function, default: null },
  dropTypes: { type: Array, default: () => [] },
})
const emit = defineEmits(["select", "open", "hover", "layout", "connect", "delete", "drop", "move"])

const NODE_TYPES = { card: markRaw(CardNode), robo: markRaw(RoboNode), region: markRaw(RegionNode), collapsed: markRaw(CollapsedNode) }
const EDGE_TYPES = { wire: markRaw(WireEdge) }
const VIRTUALIZE = 600
const MARKERS = [
  { id: "kg-arrow-ctrl", fill: "var(--kg-ctrl)" },
  { id: "kg-arrow-ctrl-robo", fill: "var(--kg-robo-flow)" },
  { id: "kg-arrow-data", fill: "var(--kg-untyped)" },
  { id: "kg-arrow-data-robo", fill: "var(--kg-robo-data)" },
]

const state = useGraphState()
const { fitView, viewport, setViewport, onViewportChange, screenToFlowCoordinate, getSelectedNodes, getSelectedEdges } = useVueFlow(props.flowId)
const root = ref(null)
const nodes = shallowRef([])
const edges = shallowRef([])
const busy = ref(false)
const error = ref(null)
const planned = ref(0)
const lod = ref("near")
let layout = null
let run = 0
let anchor = null

onViewportChange(({ zoom }) => {
  lod.value = zoom < props.lodFar ? "far" : zoom < props.lodMid ? "mid" : "near"
})

/** Keep the box of region `rid` where it is on screen across the next layout. */
function anchorRegion(rid) {
  const box = layout && [...layout.regions, ...layout.nodes].find((b) => b.region?.id === rid)
  anchor = box ? { rid, x: box.x, y: box.y } : null
}

/** Put element `id` (a node id) at `position` when it is next drawn. */
function place(id, position) {
  props.memory?.placed.set(id, { x: position.x, y: position.y })
}

/** The page point at the middle of the view. */
function center() {
  const r = root.value?.getBoundingClientRect()
  return r ? screenToFlowCoordinate({ x: r.left + r.width / 2, y: r.top + r.height / 2 }) : { x: 0, y: 0 }
}

/** Where every statement of the graph is drawn: node id -> {x, y}. */
function positions() {
  const out = new Map()
  for (const n of layout?.nodes || []) if (n.node && props.model.byId.has(n.node.id)) out.set(n.node.id, { x: n.x, y: n.y })
  return out
}

defineExpose({ anchorRegion, place, center, positions, relayout: () => relayout(true, true), fit: (opts = {}) => fitView({ padding: 0.08, maxZoom: 1.1, ...opts }) })

function toFlow(l) {
  const model = props.model
  const out = []
  for (const r of l.regions) {
    out.push({
      id: r.id,
      type: "region",
      position: { x: r.x, y: r.y },
      data: markRaw({
        rid: r.region.id,
        ownerId: r.owner?.id,
        title: r.title,
        tone: r.tone,
        w: r.w,
        h: r.h,
        ports: r.boxed ? Object.entries(r.ports).map(([handle, p]) => boxPort(r, handle, p)) : [],
      }),
      zIndex: -100 + r.depth,
      selectable: false,
      focusable: false,
      draggable: false,
    })
  }
  for (const n of l.nodes) {
    if (n.type === "collapsed") {
      const keys = regionNodes(model, n.region.id)
        .map((id) => model.byId.get(id))
        .filter((x) => x && isStatement(x))
        .map(nodeKey)
      out.push({
        id: n.id,
        type: "collapsed",
        position: { x: n.x, y: n.y },
        data: markRaw({ rid: n.region.id, tone: toneOf(n.region), geom: n.geom, keys }),
        zIndex: 1,
      })
      continue
    }
    out.push({
      id: n.id,
      type: props.view.nodeType,
      position: { x: n.x, y: n.y },
      data: markRaw({ node: n.node, geom: n.geom, key: nodeKey(n.node) }),
      zIndex: 1,
      // A terminal or flag the view adds stands for no statement
      draggable: props.editable && model.byId.has(n.id),
    })
  }
  const index = new Map([...l.nodes, ...l.regions].map((b) => [b.id, b]))
  const wires = l.edges
    .filter((e) => e.route && e.sourceHandle && e.targetHandle)
    .map((e) => {
      const s = index.get(e.source)
      const t = index.get(e.target)
      return {
        id: e.id,
        type: "wire",
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
        data: markRaw({
          ...e,
          palette: props.view.palette,
          sourceAt: s && { x: s.x, y: s.y },
          targetAt: t && { x: t.x, y: t.y },
          sourceSize: s && { w: s.w, h: s.h },
          targetSize: t && { w: t.w, h: t.h },
          sourceSide: pinAt(s, e.sourceHandle)?.side,
          targetSide: pinAt(t, e.targetHandle)?.side,
        }),
        // Under the elements, so an element's marks lie over a wire running past it
        zIndex: 0,
      }
    })
  return { nodes: out, edges: wires }
}

function boxPort(r, handle, p) {
  const [flow, dir, name] = handle.split(":")
  const side = p.x <= 0.5 ? "left" : p.x >= r.w - 0.5 ? "right" : p.y <= 0.5 ? "top" : "bottom"
  return { handle, flow, dir, name, side, x: p.x, y: p.y, color: "var(--kg-ctrl)" }
}

function toneOf(region) {
  if (region.kind === "try") return region.owner?.port === "except" ? "except" : "try"
  return region.kind === "merge" ? "loop" : region.kind
}

function show(l) {
  layout = l
  if (props.editable && props.memory) remember(props.memory, l)
  const flow = toFlow(l)
  nodes.value = flow.nodes
  edges.value = flow.edges
}

/** Lay out and draw; `refit` frames the result, `fresh` drops what an editable view kept. */
async function relayout(refit, fresh = true) {
  const mine = ++run
  busy.value = true
  error.value = null
  planned.value = props.model.graph.nodes.length
  const opts = { ...props.options, regions: props.regions, collapsed: props.collapsed, editable: props.editable }
  const keep = props.editable && props.memory && !fresh && props.memory.placed.size > 0
  try {
    await fontsReady()
    const l = keep ? await keepLayout(props.model, props.view, opts, props.memory) : await layoutView(props.model, props.view, opts)
    if (mine !== run) return
    if (!keep && props.memory) forget(props.memory)
    const before = anchor
    anchor = null
    show(l)
    emit("layout", { ms: l.ms, cached: l.cached, nodes: l.nodes.length, regions: l.regions.length, edges: l.edges.length, layout: l })
    await nextTick()
    const box = before && [...l.regions, ...l.nodes].find((b) => b.region?.id === before.rid)
    if (box && !refit) {
      const v = viewport.value
      setViewport({ x: v.x - (box.x - before.x) * v.zoom, y: v.y - (box.y - before.y) * v.zoom, zoom: v.zoom })
    } else if (refit) setTimeout(() => fitView({ padding: 0.08, maxZoom: 1.1 }), 30)
  } catch (e) {
    if (mine === run) error.value = String(e?.message || e)
  } finally {
    if (mine === run) busy.value = false
  }
}

// An editable view keeps its elements across a graph change, unless the change comes with a new relayout key
watch(
  () => [props.model, props.relayoutKey],
  (now, was) => {
    const keyChanged = !was || now[1] !== was[1]
    if (props.editable && !keyChanged) relayout(false, false)
    else relayout(true, true)
  },
  { immediate: true },
)
watch(
  () => [props.view, props.regions, props.options],
  () => relayout(true, true),
)
watch(
  () => props.collapsed,
  () => relayout(false, true),
)

// ---------------------------------------------------------------- selection and hover

function selectionOf(node) {
  const d = node.data
  if (node.type === "region") return { type: "region", id: d.rid, key: d.rid }
  if (node.type === "collapsed") return { type: "region", id: d.rid, key: d.rid }
  return { type: "node", id: d.node.id, key: d.key, node: d.node }
}

function onNodeClick({ node }) {
  state.pickedName.value = dataName(node.data?.node)
  emit("select", selectionOf(node))
}
function onEdgeClick({ edge }) {
  state.pickedName.value = null
  emit("select", { type: "edge", id: edge.id, key: edge.data.keys[0], keys: edge.data.keys })
}
function onPaneClick() {
  state.pickedName.value = null
  emit("select", null)
}
function onEnter({ node }) {
  const s = selectionOf(node)
  state.hovered.value = s.key
  state.hoveredName.value = dataName(node.data?.node)
  emit("hover", s)
}
function onLeave() {
  state.hovered.value = null
  state.hoveredName.value = null
  emit("hover", null)
}

// ---------------------------------------------------------------- editing

const isDocNode = (id) => props.model.byId.has(id)

/** Whether a wire being drawn may connect (the pins ask; Vue Flow's own check would also judge the drawn edges). */
function validConnection(c) {
  if (!props.editable || !isDocNode(c.source) || !isDocNode(c.target)) return false
  return props.isValidConnection ? props.isValidConnection(c) : true
}
state.validConnection = validConnection

function onConnect(c) {
  if (validConnection(c)) emit("connect", { source: c.source, sourceHandle: c.sourceHandle, target: c.target, targetHandle: c.targetHandle })
}

function onDragStop({ nodes: moved }) {
  if (!props.editable || !props.memory || !layout) return
  for (const n of moved) place(n.id, n.position)
  show(placeLayout(layout.plan, props.memory))
  emit(
    "move",
    moved.filter((n) => isDocNode(n.id)).map((n) => ({ id: n.id, position: { x: n.position.x, y: n.position.y } })),
  )
}

/** Delete / Backspace: the selected statements, else the selected wires (only what the document holds). */
function onKey(event) {
  if (!props.editable || (event.key !== "Delete" && event.key !== "Backspace")) return
  if (event.target?.closest?.("input, textarea, select, [contenteditable='true']")) return
  const known = new Set(props.model.edgeKeys)
  let ids = getSelectedNodes.value.map((n) => n.data?.node?.id).filter((id) => id && isDocNode(id))
  const keys = getSelectedEdges.value.flatMap((e) => e.data?.keys || []).filter((k) => known.has(k))
  const picked = state.selected.value
  if (!ids.length && !keys.length && picked != null) {
    const n = props.model.graph.nodes.find((x) => x.id === picked || nodeKey(x) === picked)
    if (n) ids = [n.id]
  }
  if (!ids.length && !keys.length) return
  event.preventDefault()
  emit("delete", { nodes: ids, edges: ids.length ? [] : keys })
}

const accepts = (event) => props.editable && props.dropTypes.some((t) => event.dataTransfer?.types?.includes(t))

function onDragOver(event) {
  if (!accepts(event)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = "copy"
}

/** A drop of an accepted type: where it landed and the innermost region box there. */
function onDrop(event) {
  if (!accepts(event)) return
  event.preventDefault()
  const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  const hits = (layout?.regions || []).filter((r) => position.x >= r.x && position.x <= r.x + r.w && position.y >= r.y && position.y <= r.y + r.h)
  hits.sort((a, b) => b.depth - a.depth)
  emit("drop", { event, position, region: hits[0]?.region.id ?? null })
  root.value?.focus()
}

const miniColor = (n) => (n.type === "region" ? "transparent" : "var(--kg-minimap-node)")
</script>
