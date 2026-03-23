<script setup>
import { useGraphStore } from '../../stores/graph.js'
import BaseNode from './BaseNode.vue'
import FunctionNode from './FunctionNode.vue'
import BranchNode from './BranchNode.vue'
import MergeNode from './MergeNode.vue'
import SwitchNode from './SwitchNode.vue'
import ParallelNode from './ParallelNode.vue'
import ValueNode from './ValueNode.vue'

const props = defineProps({ node: { type: Object, required: true } })
const graph = useGraphStore()

const HEADER_COLORS = {
  branch: '#3d2f1e',
  switch: '#2d2040',
  parallel: '#1e3d2f',
}

let _cnt = 0
function pid(label) { return `${label}-${++_cnt}-${Date.now()}` }

function addControlInput() {
  const node = graph.nodes.get(props.node.id)
  if (!node) return
  const idx = node.controlPorts.inputs.length
  node.controlPorts.inputs.push({ id: pid('cp-in'), name: `in ${idx}` })
  graph.autoResizeHeight(props.node.id)
}

function addCase() {
  const node = graph.nodes.get(props.node.id)
  if (!node) return
  const idx = node.controlPorts.outputs.length
  node.controlPorts.outputs.push({ id: pid('cp-case'), name: `case ${idx}` })
  graph.autoResizeHeight(props.node.id)
}

function removeCase(payload) {
  const node = graph.nodes.get(props.node.id)
  if (!node) return
  const idx = node.controlPorts.outputs.findIndex(p => p.id === payload.portId)
  if (idx !== -1) node.controlPorts.outputs.splice(idx, 1)
  graph.autoResizeHeight(props.node.id)
}

function addBranch() {
  const node = graph.nodes.get(props.node.id)
  if (!node) return
  const idx = node.controlPorts.outputs.length
  node.controlPorts.outputs.push({ id: pid('cp-out'), name: `out ${idx}` })
  graph.autoResizeHeight(props.node.id)
}

function removeBranch(payload) {
  const node = graph.nodes.get(props.node.id)
  if (!node) return
  const idx = node.controlPorts.outputs.findIndex(p => p.id === payload.portId)
  if (idx !== -1) node.controlPorts.outputs.splice(idx, 1)
  graph.autoResizeHeight(props.node.id)
}
</script>

<template>
  <BaseNode :node="node" :header-color="HEADER_COLORS[node.type] ?? null">
    <template #body>
      <FunctionNode v-if="node.type === 'function'" :node="node" />
      <BranchNode v-else-if="node.type === 'branch'" :node="node" />
      <MergeNode v-else-if="node.type === 'merge'" :node="node" @add-control-input="addControlInput" />
      <SwitchNode v-else-if="node.type === 'switch'" :node="node" @add-case="addCase" @remove-case="removeCase" />
      <ParallelNode v-else-if="node.type === 'parallel'" :node="node" @add-branch="addBranch" @remove-branch="removeBranch" />
      <ValueNode v-else-if="node.type === 'value'" :node="node" />
      <!-- User-defined types: render as function -->
      <FunctionNode v-else :node="node" />
    </template>
  </BaseNode>
</template>
