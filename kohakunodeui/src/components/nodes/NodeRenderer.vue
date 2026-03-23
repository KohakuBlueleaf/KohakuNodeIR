<script setup>
/**
 * NodeRenderer — dispatcher that wraps BaseNode and injects type-specific body content.
 *
 * Usage:
 *   <NodeRenderer :node="node" />
 *
 * BaseNode receives an optional `headerColor` for node types that have a
 * distinctive header tint. Type-specific components are mounted inside the
 * named #body slot.
 *
 * Event forwarding:
 *   All emitted events from child type components bubble through NodeRenderer
 *   as-is so the parent canvas / editor can handle them centrally.
 */

import BaseNode    from './BaseNode.vue';
import FunctionNode from './FunctionNode.vue';
import BranchNode   from './BranchNode.vue';
import MergeNode    from './MergeNode.vue';
import SwitchNode   from './SwitchNode.vue';
import ParallelNode from './ParallelNode.vue';
import ValueNode    from './ValueNode.vue';

const props = defineProps({
  node: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits([
  // FunctionNode
  'update:property',
  // MergeNode
  'add-control-input',
  // SwitchNode
  'add-case',
  'remove-case',
  // ParallelNode
  'add-branch',
  'remove-branch',
]);

/**
 * Map node type -> distinctive header background color.
 * null = use BaseNode's default (#313244).
 */
const HEADER_COLORS = {
  branch:   '#3d2f1e',
  switch:   '#2d2040',
  parallel: '#1e3d2f',
};

function headerColor(type) {
  return HEADER_COLORS[type] ?? null;
}
</script>

<template>
  <BaseNode :node="node" :header-color="headerColor(node.type)">
    <template #body>

      <FunctionNode
        v-if="node.type === 'function'"
        :node="node"
        @update:property="emit('update:property', $event)"
      />

      <BranchNode
        v-else-if="node.type === 'branch'"
        :node="node"
      />

      <MergeNode
        v-else-if="node.type === 'merge'"
        :node="node"
        @add-control-input="emit('add-control-input')"
      />

      <SwitchNode
        v-else-if="node.type === 'switch'"
        :node="node"
        @add-case="emit('add-case')"
        @remove-case="emit('remove-case', $event)"
      />

      <ParallelNode
        v-else-if="node.type === 'parallel'"
        :node="node"
        @add-branch="emit('add-branch')"
        @remove-branch="emit('remove-branch', $event)"
      />

      <ValueNode
        v-else-if="node.type === 'value'"
        :node="node"
        @update:property="emit('update:property', $event)"
      />

      <!-- Fallback for unknown / future node types -->
      <div v-else class="unknown-type">
        <span class="unknown-label">unknown type: {{ node.type }}</span>
      </div>

    </template>
  </BaseNode>
</template>

<style scoped>
.unknown-type {
  padding: 4px 0;
}
.unknown-label {
  font-size: 10px;
  color: #f38ba8;
  font-family: monospace;
}
</style>
