<script setup>
/**
 * BranchNode — body content for 'branch' type nodes.
 * Rendered inside BaseNode's #body slot via NodeRenderer.
 *
 * Layout:
 *   - Condition data-input port label + type indicator
 *   - Two control-output indicators: T (true) and F (false), color-coded
 *
 * The header color (#3d2f1e) is applied via BaseNode's headerColor prop
 * in NodeRenderer — this component only owns the body area.
 */

const props = defineProps({
  node: {
    type: Object,
    required: true,
  },
});

/** Pull the condition port (first data input) */
const conditionPort = props.node.dataPorts?.inputs?.[0] ?? null;
</script>

<template>
  <div class="branch-body">

    <!-- Condition input label -->
    <div class="condition-row">
      <span class="port-dot port-dot--data" />
      <span class="label">condition</span>
      <span class="type-tag">bool</span>
    </div>

    <!-- True / False output indicators -->
    <div class="outcomes">
      <div class="outcome outcome--true">
        <span class="outcome-letter">T</span>
        <span class="outcome-label">true</span>
      </div>
      <div class="outcome outcome--false">
        <span class="outcome-letter">F</span>
        <span class="outcome-label">false</span>
      </div>
    </div>

  </div>
</template>

<style scoped>
.branch-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 11px;
}

/* Condition row */
.condition-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 0;
}

.port-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.port-dot--data {
  background: #89b4fa; /* --port-data */
}

.label {
  flex: 1;
  color: #cdd6f4;
}

.type-tag {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #89b4fa;
  text-transform: lowercase;
}

/* T / F outcome pills */
.outcomes {
  display: flex;
  gap: 6px;
}

.outcome {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  padding: 3px 6px;
  border-radius: 4px;
  border: 1px solid transparent;
}

.outcome--true {
  background: rgba(166, 227, 161, 0.10);
  border-color: rgba(166, 227, 161, 0.25);
}
.outcome--false {
  background: rgba(243, 139, 168, 0.10);
  border-color: rgba(243, 139, 168, 0.25);
}

.outcome-letter {
  font-size: 11px;
  font-weight: 800;
  width: 12px;
  text-align: center;
}
.outcome--true  .outcome-letter { color: #a6e3a1; }
.outcome--false .outcome-letter { color: #f38ba8; }

.outcome-label {
  font-size: 10px;
  color: #9399b2;
}
</style>
