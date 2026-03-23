<script setup>
import { ref, computed, provide, watch, onMounted, onBeforeUnmount } from 'vue'
import { useEditorStore } from '../../stores/editor.js'
import { useGraphStore } from '../../stores/graph.js'
import { useDrag } from '../../composables/useDrag.js'
import { useResize } from '../../composables/useResize.js'
import DataPort from '../ports/DataPort.vue'
import ControlPort from '../ports/ControlPort.vue'

const HEADER_H = 32
const CTRL_ROW_H = 18
const DATA_PORT_PAD = 12

const props = defineProps({
  node: { type: Object, required: true },
  headerColor: { type: String, default: null },
})

const editorStore = useEditorStore()
const graphStore = useGraphStore()

const nodeEl = ref(null)

function getZoom() {
  return editorStore.zoom ?? 1
}

const { isDragging } = useDrag(props.node.id, nodeEl, getZoom)
const { isResizing } = useResize(props.node.id, nodeEl, getZoom)

const isSelected = computed(() => editorStore.selectedNodeIds.has(props.node.id))

function onNodeClick(e) {
  if (isDragging.value || isResizing.value) return
  const additive = e.ctrlKey || e.metaKey || e.shiftKey
  editorStore.selectNode(props.node.id, additive)
  e.stopPropagation()
}

// ── Port arrays ──
const dataInputs = computed(() => props.node.dataPorts?.inputs ?? [])
const dataOutputs = computed(() => props.node.dataPorts?.outputs ?? [])
const ctrlInputs = computed(() => props.node.controlPorts?.inputs ?? [])
const ctrlOutputs = computed(() => props.node.controlPorts?.outputs ?? [])
const hasCtrlIn = computed(() => ctrlInputs.value.length > 0)
const hasCtrlOut = computed(() => ctrlOutputs.value.length > 0)

// ── Data port circle positions (absolute relative to node root) ──
function dataPortTop(index, count) {
  const bodyTop = (hasCtrlIn.value ? CTRL_ROW_H : 0) + HEADER_H + DATA_PORT_PAD
  const bodyAvail = props.node.height - bodyTop - (hasCtrlOut.value ? CTRL_ROW_H : 0) - DATA_PORT_PAD
  if (count <= 1) return bodyTop + bodyAvail / 2
  return bodyTop + (bodyAvail / (count - 1)) * index
}

// ── Control port horizontal positions ──
function ctrlPortLeft(index, count) {
  if (count <= 1) return props.node.width / 2
  const pad = 30
  return pad + (props.node.width - pad * 2) / (count - 1) * index
}

// ── Draft wire provide ──
const draftWireType = computed(() => editorStore.draftWire?.portType ?? null)
const draftWireDir = computed(() => editorStore.isDrawingWire ? 'output' : null)
provide('draftWireType', draftWireType)
provide('draftWireDir', draftWireDir)

function onPortMouseDown(payload) {
  editorStore.startDraftWire(payload.nodeId, payload.portId, payload.portType)
}

function onPortMouseUp(payload) {
  if (!editorStore.isDrawingWire) return
  editorStore.endDraftWire(payload.nodeId, payload.portId)
}

// ── Type badge ──
const TYPE_COLORS = {
  branch: '#fab387',
  merge: '#fab387',
  switch: '#fab387',
  parallel: '#fab387',
  value: '#a6e3a1',
  function: '#89b4fa',
}
const typeBadgeColor = computed(() => TYPE_COLORS[props.node.type] ?? '#6c7086')

const nodeStyle = computed(() => ({
  left: `${props.node.x}px`,
  top: `${props.node.y}px`,
  width: `${props.node.width}px`,
  height: `${props.node.height}px`,
}))
</script>

<template>
  <div
    ref="nodeEl"
    class="node-root"
    :class="{
      'node-root--selected': isSelected,
      'node-root--dragging': isDragging,
    }"
    :style="nodeStyle"
    :data-node-id="node.id"
    @click.stop="onNodeClick"
  >
    <!-- ── Control inputs (top) ── real height row ── -->
    <div v-if="hasCtrlIn" class="ctrl-row ctrl-row--top">
      <ControlPort
        v-for="(port, i) in ctrlInputs"
        :key="port.id"
        :port="port"
        :node-id="node.id"
        direction="input"
        :port-index="i"
        :total-ports="ctrlInputs.length"
        :style="{ left: ctrlPortLeft(i, ctrlInputs.length) + 'px' }"
        @port-mousedown="onPortMouseDown"
        @port-mouseup="onPortMouseUp"
      />
    </div>

    <!-- ── Header (drag handle) ── -->
    <div
      class="node-header"
      :style="headerColor ? { background: headerColor } : {}"
    >
      <span class="node-badge" :style="{ background: typeBadgeColor }" />
      <span class="node-name">{{ node.name }}</span>
      <span class="node-type">{{ node.type }}</span>
    </div>

    <!-- ── Body ── -->
    <div class="node-body">
      <slot name="body" />
    </div>

    <!-- ── Control outputs (bottom) ── real height row ── -->
    <div v-if="hasCtrlOut" class="ctrl-row ctrl-row--bot">
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
        :style="{ left: ctrlPortLeft(i, ctrlOutputs.length) + 'px' }"
        @port-mousedown="onPortMouseDown"
        @port-mouseup="onPortMouseUp"
      />
    </div>

    <!-- ── Data port circles (absolute on node border) ── -->
    <DataPort
      v-for="(port, i) in dataInputs"
      :key="'di-' + port.id"
      :port="port"
      :node-id="node.id"
      direction="input"
      :port-index="i"
      :total-ports="dataInputs.length"
      :style="{ top: dataPortTop(i, dataInputs.length) + 'px' }"
      @port-mousedown="onPortMouseDown"
      @port-mouseup="onPortMouseUp"
    />

    <DataPort
      v-for="(port, i) in dataOutputs"
      :key="'do-' + port.id"
      :port="port"
      :node-id="node.id"
      direction="output"
      :port-index="i"
      :total-ports="dataOutputs.length"
      :style="{ top: dataPortTop(i, dataOutputs.length) + 'px' }"
      @port-mousedown="onPortMouseDown"
      @port-mouseup="onPortMouseUp"
    />
  </div>
</template>

<style scoped>
.node-root {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: #1e1e2e;
  border: 1.5px solid #45475a;
  border-radius: 8px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
  cursor: default;
  user-select: none;
  z-index: 10;
  overflow: visible;
  transition: border-color 0.12s, box-shadow 0.15s;
  box-sizing: border-box;
}
.node-root:hover { border-color: #6c8ebf; }
.node-root--selected {
  border-color: #89b4fa;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45), 0 0 0 2px rgba(137, 180, 250, 0.3), 0 0 12px 2px rgba(137, 180, 250, 0.15);
  z-index: 12;
}
.node-root--dragging { z-index: 50; opacity: 0.92; cursor: grabbing; }

/* ── Control port rows: real height, no overlap ── */
.ctrl-row {
  position: relative;
  height: 18px;
  flex-shrink: 0;
}
.ctrl-row--top { border-bottom: 1px solid #313244; }
.ctrl-row--bot { border-top: 1px solid #313244; }

/* ── Header ── */
.node-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 32px;
  background: #313244;
  border-bottom: 1px solid #45475a;
  cursor: grab;
  flex-shrink: 0;
}
.node-root--dragging .node-header { cursor: grabbing; }

.node-badge {
  flex-shrink: 0;
  width: 8px; height: 8px;
  border-radius: 50%;
  opacity: 0.85;
}
.node-name {
  flex: 1;
  font-size: 12px; font-weight: 600; color: #cdd6f4;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.node-type {
  flex-shrink: 0;
  font-size: 9px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: #6c7086;
  padding: 1px 4px; border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
}

/* ── Body ── */
.node-body {
  flex: 1;
  padding: 6px 16px;
  overflow: hidden;
}

</style>
