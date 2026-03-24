<script setup>
// ControlBlock.vue — C-shaped block for branch / switch / parallel / namespace /
//                   dataflow / subgraph AST nodes.
// Renders from AST data. Block mode is read-only.

import { defineAsyncComponent } from 'vue';
import InputChip from './InputChip.vue';

// Async import breaks the circular dependency: ControlBlock -> BlockStack -> ControlBlock
const BlockStack = defineAsyncComponent(() => import('./BlockStack.vue'));

const props = defineProps({
  block: {
    type: Object,
    required: true,
  },
});

// ── Colors ────────────────────────────────────────────────────────────────────
const TYPE_COLORS = {
  branch:    '#fab387',
  switch:    '#f9e2af',
  parallel:  '#94e2d5',
  namespace: '#cba6f7',
  dataflow:  '#89b4fa',
  subgraph:  '#b4befe',
};

function blockColor(type) {
  return TYPE_COLORS[type] ?? '#fab387';
}

// ── Icon ──────────────────────────────────────────────────────────────────────
function blockIcon(type) {
  switch (type) {
    case 'branch':    return '\u2ADD'; // ⊝
    case 'switch':    return '\u25A6'; // ▦
    case 'parallel':  return '\u2261'; // ≡
    case 'namespace': return '\u2605'; // ★
    case 'dataflow':  return '\u2BB0'; // ⮰
    case 'subgraph':  return '\u2753'; // @def
    default:          return '\u25A0';
  }
}

/**
 * Derive the arms array from the block for rendering.
 * All control block types carry .arms already from the AST walker,
 * except namespace/dataflow/subgraph which have .blocks.
 */
function arms(block) {
  if (block.arms && block.arms.length) return block.arms;
  // Namespace, dataflow, subgraph: single body arm
  if (block.blocks) return [{ label: block.label ?? block.name ?? block.type, blocks: block.blocks }];
  return [];
}

/**
 * Derive the header condition/value chip expression, if any.
 */
function headerExpr(block) {
  if (block.type === 'branch') return block.condition ?? null;
  if (block.type === 'switch') return block.value ?? null;
  return null;
}

/**
 * Header label text for the block.
 */
function headerLabel(block) {
  switch (block.type) {
    case 'branch':    return 'branch';
    case 'switch':    return 'switch';
    case 'parallel':  return 'parallel';
    case 'namespace': return block.label ?? 'namespace';
    case 'dataflow':  return '@dataflow';
    case 'subgraph':  return `@def ${block.name ?? ''}`;
    default:          return block.type;
  }
}
</script>

<template>
  <div
    class="control-block"
    :style="{ '--ctrl-color': blockColor(block.type) }"
  >
    <!-- Top notch -->
    <div class="block-notch-top" />

    <!-- ── Header section ── -->
    <div class="ctrl-header">
      <div class="ctrl-header-row">
        <span class="ctrl-icon">{{ blockIcon(block.type) }}</span>
        <span class="ctrl-name">{{ headerLabel(block) }}</span>
        <span class="ctrl-type-badge">{{ block.type }}</span>
      </div>

      <!-- Condition / value chip (branch condition, switch value) -->
      <div v-if="headerExpr(block)" class="ctrl-condition">
        <span class="ctrl-cond-label">
          {{ block.type === 'branch' ? 'if' : 'on' }}
        </span>
        <InputChip :expr="headerExpr(block)" />
      </div>

      <!-- Subgraph params -->
      <div v-if="block.type === 'subgraph' && block.params?.length" class="ctrl-params">
        <span
          v-for="p in block.params"
          :key="p"
          class="ctrl-param-chip"
        >{{ p }}</span>
      </div>

      <!-- Subgraph outputs -->
      <div v-if="block.type === 'subgraph' && block.outputs?.length" class="ctrl-sg-outputs">
        <span
          v-for="o in block.outputs"
          :key="o"
          class="ctrl-sg-output-chip"
        >&#x2192; {{ o }}</span>
      </div>
    </div>

    <!-- ── Arms (C body) ── -->
    <div class="ctrl-arms">
      <div
        v-for="(arm, i) in arms(block)"
        :key="arm.label ?? i"
        class="ctrl-arm"
      >
        <!-- Arm label (left sidebar) — for switch, shows the case expression -->
        <div class="ctrl-arm-label">
          <span class="arm-label-text">
            {{ arm.caseExpr ? arm.caseExpr.text + ' =>' : arm.label }}
          </span>
        </div>

        <!-- Arm body: indented BlockStack (read-only) -->
        <div class="ctrl-arm-body">
          <BlockStack :blocks="arm.blocks" />
        </div>
      </div>
    </div>

    <!-- ── Closing bar ── -->
    <div class="ctrl-footer" />

    <!-- Bottom bump connector -->
    <div class="block-bump-bottom" />
  </div>
</template>

<style scoped>
.control-block {
  position: relative;
  min-width: 250px;
  background: color-mix(in srgb, var(--ctrl-color) 12%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, var(--ctrl-color) 55%, transparent);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  font-size: 12px;
  color: #cdd6f4;
  user-select: none;
  padding-top: 8px;
}

/* Notch at top */
.block-notch-top {
  position: absolute;
  top: -1px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: #1e1e2e;
  border-radius: 6px 6px 0 0;
  border: 1.5px solid color-mix(in srgb, var(--ctrl-color) 55%, transparent);
  border-bottom: none;
  z-index: 2;
}

/* Header */
.ctrl-header {
  padding: 4px 12px 8px;
  border-bottom: 1.5px solid color-mix(in srgb, var(--ctrl-color) 30%, transparent);
}

.ctrl-header-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.ctrl-icon {
  font-size: 14px;
  color: var(--ctrl-color);
  line-height: 1;
}

.ctrl-name {
  font-weight: 700;
  font-size: 12px;
  color: var(--ctrl-color);
  flex: 1;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.ctrl-type-badge {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: color-mix(in srgb, var(--ctrl-color) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--ctrl-color) 30%, transparent);
  border-radius: 3px;
  padding: 1px 5px;
  color: color-mix(in srgb, var(--ctrl-color) 80%, #cdd6f4);
}

/* Condition chip row */
.ctrl-condition {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 4px;
}

.ctrl-cond-label {
  font-size: 10px;
  color: #6c7086;
  min-width: 16px;
}

/* Subgraph params */
.ctrl-params {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding-top: 4px;
}

.ctrl-param-chip {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 10px;
  background: color-mix(in srgb, var(--ctrl-color) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--ctrl-color) 30%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
  color: var(--ctrl-color);
}

/* Subgraph outputs */
.ctrl-sg-outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding-top: 4px;
}

.ctrl-sg-output-chip {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 10px;
  background: color-mix(in srgb, #a6e3a1 12%, transparent);
  border: 1px solid color-mix(in srgb, #a6e3a1 30%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
  color: #a6e3a1;
}

/* Arms container */
.ctrl-arms {
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* Single arm */
.ctrl-arm {
  display: flex;
  align-items: stretch;
  border-top: 1px solid color-mix(in srgb, var(--ctrl-color) 20%, transparent);
}

/* Vertical label strip — the "C" left wall */
.ctrl-arm-label {
  width: 24px;
  background: color-mix(in srgb, var(--ctrl-color) 20%, #181825);
  border-right: 1.5px solid color-mix(in srgb, var(--ctrl-color) 40%, transparent);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 6px;
  flex-shrink: 0;
}

.arm-label-text {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--ctrl-color);
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  opacity: 0.85;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

/* Arm body */
.ctrl-arm-body {
  flex: 1;
  padding: 8px 8px 8px 10px;
  min-height: 40px;
}

/* Closing footer bar */
.ctrl-footer {
  height: 12px;
  background: color-mix(in srgb, var(--ctrl-color) 18%, #181825);
  border-top: 1.5px solid color-mix(in srgb, var(--ctrl-color) 35%, transparent);
  border-radius: 0 0 4px 4px;
}

/* Bottom bump */
.block-bump-bottom {
  position: absolute;
  bottom: -8px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: color-mix(in srgb, var(--ctrl-color) 18%, #181825);
  border-radius: 0 0 6px 6px;
  border: 1.5px solid color-mix(in srgb, var(--ctrl-color) 55%, transparent);
  border-top: none;
  z-index: 1;
}
</style>
