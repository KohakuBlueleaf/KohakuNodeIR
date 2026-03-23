<script setup>
/**
 * BaseNode — the full node component used for ALL node types.
 *
 * Responsibilities:
 *  - Absolute positioning at node.x / node.y with node.width / node.height
 *  - Drag (via useDrag composable on the .node-header element)
 *  - Resize (via useResize composable — injects right/bottom/corner handles)
 *  - Click-to-select (reads/writes editor store's selectedNodeIds)
 *  - Renders DataPort components on left (inputs) and right (outputs) edges
 *  - Renders ControlPort components on top (inputs) and bottom (outputs) edges
 *  - Forwards port-mousedown / port-mouseup to the editor store
 *  - Provides draftWireType / draftWireDir to port children via provide()
 *  - Keyword arg default values shown as editable inline inputs
 *
 * Port position arithmetic mirrors graph.js getPortPosition() so the visual
 * circles land exactly where the store expects them.
 *
 * Layout (simplified):
 *
 *   ┌───────────────────────────────┐  ← .node-root  (position:absolute)
 *   │  ◆ ◆  ctrl-in row  ◆ ◆       │  ← .ctrl-in-row (top edge overlay)
 *   ├───────────────────────────────┤
 *   │ [badge] Node Name             │  ← .node-header  (drag handle)
 *   ├───────────────────────────────┤
 *   │ ◉ in1           out1 ◉        │  ← .node-body  (data ports + keyword args)
 *   │ ◉ in2           out2 ◉        │
 *   │ ◇ kw = <input>                │
 *   ├───────────────────────────────┤
 *   │  ◆ ◆  ctrl-out row  ◆ ◆      │  ← .ctrl-out-row (bottom edge overlay)
 *   └───────────────────────────────┘
 *                                    ↘ resize handles injected by useResize
 */

import { ref, computed, provide, watch, onMounted, onBeforeUnmount } from 'vue'
import { useEditorStore } from '../../stores/editor.js'
import { useGraphStore  } from '../../stores/graph.js'
import { useDrag        } from '../../composables/useDrag.js'
import { useResize      } from '../../composables/useResize.js'
import DataPort    from '../ports/DataPort.vue'
import ControlPort from '../ports/ControlPort.vue'

// ---- Props ----------------------------------------------------------------

const props = defineProps({
  /** Full node data object from the graph store */
  node: {
    type: Object,
    required: true,
  },
  /**
   * Optional CSS color string to override the header background.
   * Used by NodeRenderer to give control-flow node types a distinct tint.
   */
  headerColor: {
    type: String,
    default: null,
  },
})

// ---- Stores ---------------------------------------------------------------

const editorStore = useEditorStore()
const graphStore  = useGraphStore()

// ---- Template refs --------------------------------------------------------

/** Root element ref — passed to composables */
const nodeEl = ref(null)

// ---- Zoom accessor (composables need a getter, not a reactive ref) ---------

function getZoom() {
  return editorStore.zoom ?? 1
}

// ---- Drag -----------------------------------------------------------------

const { isDragging } = useDrag(props.node.id, nodeEl, getZoom)

// ---- Resize ---------------------------------------------------------------

const { isResizing } = useResize(props.node.id, nodeEl, getZoom)

// ---- Selection ------------------------------------------------------------

const isSelected = computed(() =>
  editorStore.selectedNodeIds.has(props.node.id)
)

function onNodeClick(e) {
  // Don't treat drag-end as a selection click
  if (isDragging.value || isResizing.value) return
  const additive = e.ctrlKey || e.metaKey || e.shiftKey
  editorStore.selectNode(props.node.id, additive)
  e.stopPropagation()
}

// ---- Port geometry --------------------------------------------------------

/**
 * Constants must stay in sync with graph.js
 * PORT_PADDING = 20, PORT_SPACING = 24 (implied by evenSpacing formula)
 */
const PORT_PADDING = 20

/**
 * Replicates the graph store's evenSpacing helper so DataPort / ControlPort
 * components can be placed at the correct pixel offsets within the node,
 * matching getPortPosition() in canvas space.
 *
 * @param {number} index
 * @param {number} count
 * @param {number} span   — node height (for data) or node width (for control)
 * @returns {number}  offset from the edge start in px
 */
function evenSpacing(index, count, span) {
  if (count === 1) return span / 2
  return PORT_PADDING + index * ((span - PORT_PADDING * 2) / (count - 1))
}

// ---- Computed port arrays -------------------------------------------------

const dataInputs   = computed(() => props.node.dataPorts?.inputs  ?? [])
const dataOutputs  = computed(() => props.node.dataPorts?.outputs ?? [])
const ctrlInputs   = computed(() => props.node.controlPorts?.inputs  ?? [])
const ctrlOutputs  = computed(() => props.node.controlPorts?.outputs ?? [])

const hasControlPorts = computed(() =>
  ctrlInputs.value.length > 0 || ctrlOutputs.value.length > 0
)

const hasDataPorts = computed(() =>
  dataInputs.value.length > 0 || dataOutputs.value.length > 0
)

// ---- Port styles (inline `top` for data, inline `left` for control) -------

function dataPortStyle(index, count) {
  const offset = evenSpacing(index, count, props.node.height)
  return { top: `${offset}px` }
}

function ctrlPortStyle(index, count) {
  const offset = evenSpacing(index, count, props.node.width)
  return { left: `${offset}px` }
}

// ---- Draft wire provide ---------------------------------------------------

/**
 * Provide reactive context so port children can highlight when a compatible
 * draft wire is being drawn.
 */
const draftWireType = computed(() => editorStore.draftWire?.portType ?? null)
const draftWireDir  = computed(() => editorStore.isDrawingWire ? 'output' : null)

provide('draftWireType', draftWireType)
provide('draftWireDir',  draftWireDir)

// ---- Wire drawing events --------------------------------------------------

function onPortMouseDown(payload) {
  // Only output ports emit this
  editorStore.startDraftWire(payload.nodeId, payload.portId, payload.portType)
}

function onPortMouseUp(payload) {
  // Only input ports emit this
  if (!editorStore.isDrawingWire) return
  editorStore.endDraftWire(payload.nodeId, payload.portId)
}

// ---- Keyword args with defaults ------------------------------------------

/**
 * Return whether a data-input port has a default value that should be shown
 * as an editable field (only when the port has no incoming connection).
 */
function portHasDefault(port) {
  return port.defaultValue !== undefined && port.defaultValue !== null
}

function portIsConnected(portId) {
  return graphStore.getPortConnections(portId).length > 0
}

/** Local editable state for default values, keyed by port.id */
const localDefaults = ref({})

function initLocalDefaults() {
  const defaults = {}
  for (const port of dataInputs.value) {
    if (portHasDefault(port)) {
      defaults[port.id] = String(port.defaultValue)
    }
  }
  localDefaults.value = defaults
}

onMounted(initLocalDefaults)
watch(() => props.node.dataPorts?.inputs, initLocalDefaults, { deep: true })

function onDefaultInput(port, e) {
  localDefaults.value[port.id] = e.target.value
  // Reflect the change back onto the port's defaultValue through the graph store.
  // The graph store keeps the node reactive; we reach into the port directly
  // since there is no dedicated store action for port default values yet.
  const livePort = graphStore.nodes.get(props.node.id)
    ?.dataPorts.inputs.find(p => p.id === port.id)
  if (livePort) livePort.defaultValue = e.target.value
}

// ---- Node type badge color ------------------------------------------------

const TYPE_COLORS = {
  branch:   '#fab387',  // orange — control flow
  merge:    '#fab387',
  switch:   '#fab387',
  parallel: '#fab387',
  value:    '#a6e3a1',  // green  — data
  function: '#89b4fa',  // blue   — generic
}

const typeBadgeColor = computed(() =>
  TYPE_COLORS[props.node.type] ?? '#6c7086'
)

// ---- Root styles ----------------------------------------------------------

const nodeStyle = computed(() => ({
  left:   `${props.node.x}px`,
  top:    `${props.node.y}px`,
  width:  `${props.node.width}px`,
  height: `${props.node.height}px`,
}))
</script>

<template>
  <div
    ref="nodeEl"
    class="node-root"
    :class="{
      'node-root--selected':  isSelected,
      'node-root--dragging':  isDragging,
      'node-root--resizing':  isResizing,
    }"
    :style="nodeStyle"
    :data-node-id="node.id"
    @click.stop="onNodeClick"
  >
    <!-- ================================================================
         CONTROL INPUT PORTS — top edge
    ================================================================== -->
    <div v-if="ctrlInputs.length" class="ctrl-in-row">
      <ControlPort
        v-for="(port, i) in ctrlInputs"
        :key="port.id"
        :port="port"
        :node-id="node.id"
        direction="input"
        :port-index="i"
        :total-ports="ctrlInputs.length"
        :label="node.type === 'branch' && port.name === 'in' ? '' : null"
        :style="ctrlPortStyle(i, ctrlInputs.length)"
        @port-mousedown="onPortMouseDown"
        @port-mouseup="onPortMouseUp"
      />
    </div>

    <!-- ================================================================
         HEADER — drag handle
    ================================================================== -->
    <div
      class="node-header"
      :style="headerColor ? { background: headerColor, borderBottomColor: headerColor } : {}"
    >
      <!-- Type badge -->
      <span
        class="node-type-badge"
        :style="{ background: typeBadgeColor }"
        :title="node.type"
      />
      <!-- Name -->
      <span class="node-name">{{ node.name }}</span>
      <!-- Type label (small, right-aligned) -->
      <span class="node-type-label">{{ node.type }}</span>
    </div>

    <!-- ================================================================
         BODY — data ports + keyword arg defaults
    ================================================================== -->
    <div class="node-body">
      <!-- DATA INPUT ports (left edge) -->
      <DataPort
        v-for="(port, i) in dataInputs"
        :key="port.id"
        :port="port"
        :node-id="node.id"
        direction="input"
        :port-index="i"
        :total-ports="dataInputs.length"
        :style="dataPortStyle(i, dataInputs.length)"
        @port-mousedown="onPortMouseDown"
        @port-mouseup="onPortMouseUp"
      />

      <!-- DATA OUTPUT ports (right edge) -->
      <DataPort
        v-for="(port, i) in dataOutputs"
        :key="port.id"
        :port="port"
        :node-id="node.id"
        direction="output"
        :port-index="i"
        :total-ports="dataOutputs.length"
        :style="dataPortStyle(i, dataOutputs.length)"
        @port-mousedown="onPortMouseDown"
        @port-mouseup="onPortMouseUp"
      />

      <!-- Keyword arg default-value rows
           Only rendered for input ports that have a default AND are not
           currently connected. These float in the center of the body. -->
      <div
        v-for="port in dataInputs.filter(p => portHasDefault(p) && !portIsConnected(p.id))"
        :key="`kw-${port.id}`"
        class="kw-row"
      >
        <span class="kw-name">{{ port.name }}</span>
        <span class="kw-eq">=</span>
        <input
          class="kw-input"
          type="text"
          :value="localDefaults[port.id] ?? String(port.defaultValue)"
          @input="onDefaultInput(port, $event)"
          @mousedown.stop
          @click.stop
        />
      </div>

      <!-- Type-specific body content from specialized node components -->
      <slot name="body" />

      <!-- Empty body placeholder so nodes with no data ports still have height -->
      <div
        v-if="!hasDataPorts && !hasControlPorts && !$slots.body"
        class="node-empty"
      >
        no ports
      </div>
    </div>

    <!-- ================================================================
         CONTROL OUTPUT PORTS — bottom edge
    ================================================================== -->
    <div v-if="ctrlOutputs.length" class="ctrl-out-row">
      <ControlPort
        v-for="(port, i) in ctrlOutputs"
        :key="port.id"
        :port="port"
        :node-id="node.id"
        direction="output"
        :port-index="i"
        :total-ports="ctrlOutputs.length"
        :label="
          node.type === 'branch'
            ? (port.name === 'true' ? 'T' : port.name === 'false' ? 'F' : null)
            : null
        "
        :style="ctrlPortStyle(i, ctrlOutputs.length)"
        @port-mousedown="onPortMouseDown"
        @port-mouseup="onPortMouseUp"
      />
    </div>

    <!-- Resize handles are injected into nodeEl by useResize on mount -->
  </div>
</template>

<style scoped>
/* ================================================================== */
/* Root                                                                 */
/* ================================================================== */
.node-root {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: #1e1e2e;
  border: 1.5px solid #45475a;
  border-radius: 8px;
  box-shadow:
    0 2px 6px rgba(0, 0, 0, 0.45),
    0 0 0 0 rgba(137, 180, 250, 0);
  cursor: default;
  user-select: none;
  z-index: 10;
  overflow: visible;          /* ports bleed outside the border */
  transition:
    border-color 0.12s,
    box-shadow   0.15s;
  box-sizing: border-box;
}

/* Hover — subtle blue tint on border */
.node-root:hover {
  border-color: #6c8ebf;
}

/* Selected */
.node-root--selected {
  border-color: #89b4fa;
  box-shadow:
    0 2px 6px rgba(0, 0, 0, 0.45),
    0 0 0 2px rgba(137, 180, 250, 0.30),
    0 0 12px 2px rgba(137, 180, 250, 0.15);
  z-index: 12;
}

/* Dragging — elevate above siblings */
.node-root--dragging {
  z-index: 50;
  opacity: 0.92;
  cursor: grabbing;
}

/* Resizing */
.node-root--resizing {
  z-index: 50;
}

/* ================================================================== */
/* Control port rows (top / bottom overlays)                           */
/* ================================================================== */

/* Both rows sit OUTSIDE the main flex flow so they overlay the border */
.ctrl-in-row,
.ctrl-out-row {
  position: absolute;
  left: 0;
  width: 100%;
  height: 0;           /* zero height — ports bleed via translate */
  pointer-events: none; /* let children handle events */
  z-index: 15;
}

.ctrl-in-row  { top:    0; }
.ctrl-out-row { bottom: 0; }

/* Re-enable pointer events on the port children themselves */
.ctrl-in-row  :deep(.ctrl-port),
.ctrl-out-row :deep(.ctrl-port) {
  pointer-events: all;
}

/* ================================================================== */
/* Header                                                               */
/* ================================================================== */
.node-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px 5px;
  background: #313244;
  border-bottom: 1px solid #45475a;
  border-radius: 7px 7px 0 0;  /* match root border-radius on top corners */
  cursor: grab;
  flex-shrink: 0;
  min-height: 30px;
  /* useDrag looks for .node-header on mount */
}

.node-root--dragging .node-header {
  cursor: grabbing;
}

/* Small colored circle indicating node type */
.node-type-badge {
  flex-shrink: 0;
  width:  8px;
  height: 8px;
  border-radius: 50%;
  opacity: 0.85;
}

.node-name {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: #cdd6f4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
}

.node-type-label {
  flex-shrink: 0;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6c7086;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
}

/* ================================================================== */
/* Body                                                                 */
/* ================================================================== */
.node-body {
  position: relative;  /* data ports use position:absolute relative to this */
  flex: 1;
  min-height: 40px;
  padding: 8px 14px;   /* horizontal padding keeps labels away from port circles */
  overflow: visible;
}

/* ================================================================== */
/* Keyword arg rows                                                     */
/* ================================================================== */
.kw-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 4px 0;
  /* Center vertically in the body */
  position: relative;
  z-index: 1;
}

.kw-name {
  font-size: 11px;
  color: #a6adc8;
  min-width: 0;
  flex-shrink: 0;
}

.kw-eq {
  font-size: 11px;
  color: #6c7086;
}

.kw-input {
  flex: 1;
  min-width: 0;
  max-width: 90px;
  font-size: 11px;
  background: #11111b;
  color: #cdd6f4;
  border: 1px solid #45475a;
  border-radius: 3px;
  padding: 1px 5px;
  outline: none;
  transition: border-color 0.1s;
  font-family: ui-monospace, monospace;
}

.kw-input:focus {
  border-color: #89b4fa;
  background: #1e1e2e;
}

/* ================================================================== */
/* Empty-state                                                          */
/* ================================================================== */
.node-empty {
  font-size: 10px;
  color: #45475a;
  text-align: center;
  padding: 8px 0;
  pointer-events: none;
}

/* ================================================================== */
/* Resize handles injected by useResize — unscoped so they apply to
   dynamically created DOM nodes                                        */
/* ================================================================== */
</style>

<!--
  NOTE: useResize injects handles as real DOM nodes (not Vue components),
  so their styles are applied inline by the composable itself.
  No extra CSS is needed here for the handles.
-->
