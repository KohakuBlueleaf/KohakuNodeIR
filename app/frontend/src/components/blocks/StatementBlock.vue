<script setup>
// StatementBlock.vue — rectangular block for FuncCall AST nodes.
// Renders from AST data: { type: 'statement', key, funcName, inputs, outputs }
// Block mode is read-only: no drag, no delete.

import InputChip from './InputChip.vue';

const props = defineProps({
  block: {
    type: Object,
    required: true,
  },
});

// ── Function name → accent color (Catppuccin Mocha palette) ───────────────────
const FUNC_COLORS = {
  print:         '#89dceb',
  display:       '#89dceb',
  store:         '#a6e3a1',
  load:          '#a6e3a1',
  add:           '#89b4fa',
  subtract:      '#89b4fa',
  multiply:      '#89b4fa',
  divide:        '#89b4fa',
  mod:           '#89b4fa',
  pow:           '#89b4fa',
  greater_than:  '#f9e2af',
  less_than:     '#f9e2af',
  equal:         '#f9e2af',
  not_equal:     '#f9e2af',
  and:           '#f9e2af',
  or:            '#f9e2af',
  not:           '#f9e2af',
  concat:        '#a6e3a1',
  format_string: '#a6e3a1',
  read_file:     '#cba6f7',
  write_file:    '#cba6f7',
  to_int:        '#74c7ec',
  to_float:      '#74c7ec',
  to_string:     '#74c7ec',
};

function blockColor(funcName) {
  return FUNC_COLORS[funcName] ?? '#89b4fa';
}
</script>

<template>
  <div
    class="statement-block"
    :style="{ '--block-color': blockColor(block.funcName) }"
  >
    <!-- Top notch indent (accepts snap from block above) -->
    <div class="block-notch-top" />

    <!-- Header row -->
    <div class="block-header">
      <span class="block-name">{{ block.funcName }}</span>
    </div>

    <!-- Ports row: inputs on left, outputs on right -->
    <div v-if="block.inputs.length || block.outputs.length" class="block-ports">
      <!-- Data inputs -->
      <div class="block-inputs">
        <div
          v-for="(inp, i) in block.inputs"
          :key="i"
          class="block-input-row"
        >
          <InputChip :expr="inp" />
        </div>
      </div>

      <!-- Data outputs (variable names defined by this call) -->
      <div v-if="block.outputs.length" class="block-outputs">
        <div
          v-for="out in block.outputs"
          :key="out"
          class="block-output-row"
        >
          <span class="output-varname">{{ out }}</span>
          <span class="output-arrow">&#x2192;</span>
        </div>
      </div>
    </div>

    <!-- Bottom bump connector -->
    <div class="block-bump-bottom" />
  </div>
</template>

<style scoped>
.statement-block {
  position: relative;
  min-width: 200px;
  background: color-mix(in srgb, var(--block-color) 14%, #1e1e2e);
  border: 1.5px solid color-mix(in srgb, var(--block-color) 60%, transparent);
  border-radius: 4px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
  font-size: 12px;
  color: #cdd6f4;
  user-select: none;
  padding-top: 8px;
  padding-bottom: 10px;
}

/* Top notch */
.block-notch-top {
  position: absolute;
  top: -1px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: #1e1e2e;
  border-radius: 6px 6px 0 0;
  border: 1.5px solid color-mix(in srgb, var(--block-color) 60%, transparent);
  border-bottom: none;
  z-index: 2;
}

.block-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px 6px;
  border-bottom: 1px solid color-mix(in srgb, var(--block-color) 25%, transparent);
}

.block-name {
  font-weight: 700;
  font-size: 12px;
  color: var(--block-color);
  flex: 1;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

/* Two-column port layout */
.block-ports {
  display: flex;
  gap: 8px;
  padding: 6px 10px 2px;
}

.block-inputs {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.block-outputs {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-end;
}

.block-input-row,
.block-output-row {
  display: flex;
  align-items: center;
  gap: 5px;
}

.output-varname {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 10px;
  color: color-mix(in srgb, var(--block-color) 80%, #cdd6f4);
  text-align: right;
}

.output-arrow {
  font-size: 10px;
  color: color-mix(in srgb, var(--block-color) 60%, #6c7086);
}

/* Bottom bump */
.block-bump-bottom {
  position: absolute;
  bottom: -8px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 8px;
  background: color-mix(in srgb, var(--block-color) 14%, #1e1e2e);
  border-radius: 0 0 6px 6px;
  border: 1.5px solid color-mix(in srgb, var(--block-color) 60%, transparent);
  border-top: none;
  z-index: 1;
}
</style>
