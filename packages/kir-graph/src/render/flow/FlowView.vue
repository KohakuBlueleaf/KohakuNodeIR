<template>
  <div class="kg-flow" :class="[`kg-lod--${lod}`, `kg-palette--${view.palette || 'gem'}`]">
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
      :nodes-draggable="false"
      :nodes-connectable="false"
      :elements-selectable="true"
      :only-render-visible-elements="nodes.length > VIRTUALIZE"
      :min-zoom="0.03"
      :max-zoom="2.5"
      :delete-key-code="null"
      @node-click="onNodeClick"
      @edge-click="onEdgeClick"
      @node-mouse-enter="onEnter"
      @node-mouse-leave="onLeave"
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
})
const emit = defineEmits(["select", "hover", "layout"])

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
const { fitView, viewport, setViewport, onViewportChange } = useVueFlow(props.flowId)
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
defineExpose({ anchorRegion, fit: () => fitView({ padding: 0.08, maxZoom: 1.1 }) })

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
    })
  }
  const wires = l.edges
    .filter((e) => e.route && e.sourceHandle && e.targetHandle)
    .map((e) => ({
      id: e.id,
      type: "wire",
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
      data: markRaw({ ...e, palette: props.view.palette }),
      // Under the elements, so an element's marks lie over a wire running past it
      zIndex: 0,
    }))
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

async function relayout(refit) {
  const mine = ++run
  busy.value = true
  error.value = null
  planned.value = props.model.graph.nodes.length
  try {
    await fontsReady()
    const l = await layoutView(props.model, props.view, { ...props.options, regions: props.regions, collapsed: props.collapsed })
    if (mine !== run) return
    const before = anchor
    anchor = null
    layout = l
    const flow = toFlow(l)
    nodes.value = flow.nodes
    edges.value = flow.edges
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

watch(
  () => [props.model, props.view, props.regions, props.options],
  () => relayout(true),
  { immediate: true },
)
watch(
  () => props.collapsed,
  () => relayout(false),
)

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

const miniColor = (n) => (n.type === "region" ? "transparent" : "var(--kg-minimap-node)")
</script>
