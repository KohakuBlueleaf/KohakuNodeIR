<script setup>
// HatBlock.vue — entry-point hat block for standalone Namespace AST nodes.
// Renders: { type: 'namespace', key, label, blocks }
// Block mode is read-only.

import { defineAsyncComponent } from "vue";

// Async import to break potential circular dependency if namespaces nest
const BlockStack = defineAsyncComponent(() => import("./BlockStack.vue"));

const props = defineProps({
  block: {
    type: Object,
    required: true,
  },
});
</script>

<template>
  <div class="hat-block">
    <!-- Hat curve at top -->
    <div class="hat-top">
      <svg class="hat-curve" viewBox="0 0 200 20" preserveAspectRatio="none">
        <path d="M0,20 Q100,0 200,20 Z" fill="#cba6f7" />
      </svg>
      <div class="hat-header">
        <span class="hat-icon">&#x2605;</span>
        <span class="hat-label">{{ block.label }}</span>
        <span class="hat-type-badge">namespace</span>
      </div>
    </div>

    <!-- Namespace body blocks (indented) -->
    <div v-if="block.blocks && block.blocks.length" class="hat-body">
      <BlockStack :blocks="block.blocks" />
    </div>

    <!-- Bottom bump connector -->
    <div class="block-bump-bottom" />
  </div>
</template>

<style scoped>
.hat-block {
  position: relative;
  min-width: 200px;
  background: color-mix(in srgb, #cba6f7 12%, #1e1e2e);
  border-radius: 12px 12px 4px 4px;
  border: 1.5px solid #b4befe;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  font-size: 12px;
  color: #cdd6f4;
  user-select: none;
  padding-bottom: 10px;
}

/* Hat-shaped top — SVG arc overlay */
.hat-top {
  position: relative;
  border-radius: 12px 12px 0 0;
  overflow: hidden;
  background: #cba6f7;
}

.hat-curve {
  position: absolute;
  top: -1px;
  left: 0;
  width: 100%;
  height: 20px;
  pointer-events: none;
}

.hat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 14px 12px 8px;
  font-weight: 700;
  font-size: 12px;
}

.hat-icon {
  font-size: 10px;
  opacity: 0.7;
  color: #1e1e2e;
}

.hat-label {
  flex: 1;
  font-size: 13px;
  font-weight: 700;
  color: #1e1e2e;
  font-family: "JetBrains Mono", "Fira Code", monospace;
}

.hat-type-badge {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: rgba(30, 30, 46, 0.25);
  border-radius: 3px;
  padding: 1px 5px;
  color: #1e1e2e;
}

/* Namespace body blocks */
.hat-body {
  padding: 8px 8px 0 10px;
}

/* Bottom bump */
.block-bump-bottom {
  position: absolute;
  bottom: -8px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: color-mix(in srgb, #cba6f7 12%, #1e1e2e);
  border-radius: 0 0 6px 6px;
  border: 1.5px solid #b4befe;
  border-top: none;
  z-index: 1;
}
</style>
