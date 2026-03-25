<script setup>
// BlockStack.vue — renders a vertical list of AST-based block objects.
// Used for top-level stacks on the canvas AND inside C-block arms.
// Mutual recursion with ControlBlock is handled via defineAsyncComponent.

import { defineAsyncComponent } from "vue";
import HatBlock from "./HatBlock.vue";
import StatementBlock from "./StatementBlock.vue";

// Async import breaks the circular dependency: BlockStack -> ControlBlock -> BlockStack
const ControlBlock = defineAsyncComponent(() => import("./ControlBlock.vue"));

const props = defineProps({
  /** Array of Block objects from blockTree.js (AST-based) */
  blocks: {
    type: Array,
    required: true,
  },
});

/**
 * Determine if a block should use the ControlBlock component (C-block shape).
 * 'namespace' is handled above by HatBlock and never reaches this check.
 * @param {object} block
 * @returns {boolean}
 */
function isControlBlock(block) {
  return (
    block.type === "branch" ||
    block.type === "switch" ||
    block.type === "parallel" ||
    block.type === "dataflow" ||
    block.type === "subgraph"
  );
}
</script>

<template>
  <div class="block-stack">
    <template v-for="block in blocks" :key="block.key">
      <!-- Namespace hat (standalone namespace not consumed as a branch arm) -->
      <HatBlock
        v-if="block.type === 'namespace'"
        :block="block"
        class="stack-item"
      />

      <!-- C-blocks: branch / switch / parallel / dataflow / subgraph -->
      <ControlBlock
        v-else-if="isControlBlock(block)"
        :block="block"
        class="stack-item"
      />

      <!-- Assignment: target = expr -->
      <div
        v-else-if="block.type === 'assignment'"
        class="stack-item assignment-block"
      >
        <span class="assign-target">{{ block.target }}</span>
        <span class="assign-eq">=</span>
        <span class="assign-value">{{ block.value?.text ?? "" }}</span>
      </div>

      <!-- Jump -->
      <div v-else-if="block.type === 'jump'" class="stack-item jump-block">
        <span class="jump-icon">&#x21B7;</span>
        <span class="jump-target"
          >goto <code>{{ block.target }}</code></span
        >
      </div>

      <!-- Mode declaration -->
      <div v-else-if="block.type === 'mode'" class="stack-item mode-block">
        <span class="mode-label">@mode {{ block.mode }}</span>
      </div>

      <!-- KIR fallback line (shown when Pyodide is not available) -->
      <div
        v-else-if="block.type === 'kir-line'"
        class="stack-item kir-line-block"
      >
        <code class="kir-line-text">{{ block.text }}</code>
      </div>

      <!-- Default: FuncCall statement block -->
      <StatementBlock v-else :block="block" class="stack-item" />
    </template>

    <!-- Empty arm placeholder -->
    <div v-if="!blocks.length" class="stack-empty">
      <span class="stack-empty-label">empty</span>
    </div>
  </div>
</template>

<style scoped>
.block-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Each block item needs relative positioning so bumps/notches layer correctly */
.stack-item {
  position: relative;
}

/* ── Assignment block ── */
.assignment-block {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: color-mix(in srgb, #89dceb 12%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, #89dceb 45%, transparent);
  border-radius: 4px;
  padding: 5px 10px;
  font-size: 12px;
  color: #cdd6f4;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  user-select: none;
}

.assign-target {
  color: #89dceb;
  font-weight: 700;
}

.assign-eq {
  color: #6c7086;
  font-size: 11px;
}

.assign-value {
  color: #a6adc8;
}

/* ── Jump block ── */
.jump-block {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: color-mix(in srgb, #f38ba8 10%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, #f38ba8 40%, transparent);
  border-radius: 4px;
  padding: 5px 10px;
  font-size: 12px;
  color: #f38ba8;
  user-select: none;
}

.jump-icon {
  font-size: 13px;
}

.jump-target {
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 11px;
  color: #cdd6f4;
}

.jump-target code {
  color: #f38ba8;
  font-size: 11px;
}

/* ── Mode declaration block ── */
.mode-block {
  display: inline-flex;
  align-items: center;
  background: color-mix(in srgb, #cba6f7 10%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, #cba6f7 35%, transparent);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 11px;
  user-select: none;
}

.mode-label {
  font-family: "JetBrains Mono", "Fira Code", monospace;
  color: #cba6f7;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
}

/* ── KIR fallback line ── */
.kir-line-block {
  display: flex;
  align-items: center;
  background: color-mix(in srgb, #585b70 12%, #1e1e2e);
  border: 1.5px solid #313244;
  border-radius: 4px;
  padding: 5px 10px;
  user-select: none;
}

.kir-line-text {
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 11px;
  color: #a6adc8;
  white-space: pre;
}

/* ── Empty arm indicator ── */
.stack-empty {
  min-width: 120px;
  min-height: 28px;
  border: 1.5px dashed #313244;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stack-empty-label {
  font-size: 10px;
  color: #45475a;
  font-style: italic;
}
</style>
