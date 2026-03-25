<script setup>
// InputChip.vue — read-only pill that displays a single AST expression.
// Used in StatementBlock and ControlBlock to show inputs/conditions.
//
// expr shape: { kind: 'var'|'literal'|'kwarg'|'label'|'wildcard'|'empty', text: string }

const props = defineProps({
  expr: {
    type: Object,
    required: true,
  },
});

// ── kind → accent color ───────────────────────────────────────────────────────
const KIND_COLORS = {
  var: "#89b4fa", // variable reference — blue
  literal: "#a6e3a1", // literal value — green
  kwarg: "#f9e2af", // keyword arg — yellow
  label: "#cba6f7", // label ref — mauve
  wildcard: "#6c7086", // discard _ — overlay
  empty: "#45475a", // empty slot — surface2
  unknown: "#f38ba8", // unknown — red
};

function chipColor(kind) {
  return KIND_COLORS[kind] ?? KIND_COLORS.unknown;
}

function displayText(expr) {
  if (!expr || expr.kind === "empty") return "…";
  return expr.text || "…";
}
</script>

<template>
  <span
    class="input-chip"
    :style="{ '--chip-color': chipColor(expr.kind) }"
    :title="expr.kind + ': ' + expr.text"
  >
    <!-- Small dot indicator for variable references -->
    <span v-if="expr.kind === 'var'" class="chip-dot" />
    <!-- Label backtick prefix -->
    <span v-if="expr.kind === 'label'" class="chip-prefix">`</span>
    <span class="chip-text">{{ displayText(expr) }}</span>
    <span v-if="expr.kind === 'label'" class="chip-prefix">`</span>
  </span>
</template>

<style scoped>
.input-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  background: color-mix(in srgb, var(--chip-color) 16%, #1e1e2e);
  border: 1px solid color-mix(in srgb, var(--chip-color) 50%, transparent);
  border-radius: 999px;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 11px;
  color: var(--chip-color);
  white-space: nowrap;
  vertical-align: middle;
  line-height: 1.4;
  user-select: none;
}

.chip-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--chip-color);
  flex-shrink: 0;
}

.chip-prefix {
  font-size: 10px;
  opacity: 0.6;
}

.chip-text {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
