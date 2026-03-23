<script setup>
/**
 * ControlPort — diamond-shaped port on the top (input) or bottom (output)
 * edge of a node.
 *
 * Positioning: the diamond sits exactly on the node's horizontal edge.
 *   - Input (top):    translateY(-50%)  ← centered on the top border
 *   - Output (bottom):translateY(50%)   ← centered on the bottom border
 *
 * Horizontal placement is set by the parent (BaseNode) via an inline `left`
 * style passed through the `style` attribute.
 *
 * Wire drawing mirrors DataPort:
 *   - Mousedown on an OUTPUT port → emits 'port-mousedown'
 *   - Mouseup   on an INPUT  port → emits 'port-mouseup'
 */

import { ref, computed, inject } from 'vue'

const props = defineProps({
  /** Port data object from node.controlPorts.inputs[i] / .outputs[i] */
  port: {
    type: Object,
    required: true,
  },
  /** Owning node id */
  nodeId: {
    type: String,
    required: true,
  },
  /** 'input' | 'output' */
  direction: {
    type: String,
    required: true,
    validator: v => ['input', 'output'].includes(v),
  },
  /** 0-based index within the input or output port list */
  portIndex: {
    type: Number,
    required: true,
  },
  /** Total count of ports on this side */
  totalPorts: {
    type: Number,
    required: true,
  },
  /**
   * Optional short label rendered adjacent to the diamond.
   * Used for branch true/false labels ("T" / "F").
   */
  label: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['port-mousedown', 'port-mouseup'])

// ---- hover state ----
const isHovered = ref(false)

// ---- draft-wire compatibility highlight ----
const draftWireType = inject('draftWireType', null)
const draftWireDir  = inject('draftWireDir',  null)

const isCompatible = computed(() => {
  if (!draftWireType?.value) return false
  return draftWireType.value === 'control' && props.direction === 'input'
})

// ---- position modifier ----
const isOutput = computed(() => props.direction === 'output')

const portStyle = computed(() => ({
  transform: isOutput.value ? 'translateX(-50%) translateY(50%)' : 'translateX(-50%) translateY(-50%)',
}))

// ---- interaction ----
function onMouseDown(e) {
  if (props.direction !== 'output') return
  e.stopPropagation()
  e.preventDefault()
  emit('port-mousedown', {
    nodeId:    props.nodeId,
    portId:    props.port.id,
    portType:  'control',
    direction: props.direction,
    event:     e,
  })
}

function onMouseUp(e) {
  if (props.direction !== 'input') return
  e.stopPropagation()
  emit('port-mouseup', {
    nodeId:    props.nodeId,
    portId:    props.port.id,
    portType:  'control',
    direction: props.direction,
    event:     e,
  })
}

function onMouseEnter() { isHovered.value = true  }
function onMouseLeave() { isHovered.value = false }

// ---- display label ----
// Prefer the explicit `label` prop, fall back to port.name if short enough
const displayLabel = computed(() => {
  if (props.label) return props.label
  // Use port name directly — it's short for control ports ("in", "out 0", "true", etc.)
  return props.port.name
})
</script>

<template>
  <div
    class="ctrl-port"
    :class="[
      `ctrl-port--${direction}`,
      { 'ctrl-port--hovered':    isHovered    },
      { 'ctrl-port--compatible': isCompatible },
    ]"
    :style="portStyle"
    :data-port-id="port.id"
    :data-node-id="nodeId"
    data-port-type="control"
    :data-port-dir="direction"
    @mousedown="onMouseDown"
    @mouseup="onMouseUp"
    @mouseenter="onMouseEnter"
    @mouseleave="onMouseLeave"
  >
    <!-- Diamond shape (square rotated 45 deg) -->
    <div class="ctrl-port__diamond" />

    <!-- Short label below (output) or above (input) the diamond -->
    <span
      class="ctrl-port__label"
      :class="`ctrl-port__label--${direction}`"
    >
      {{ displayLabel }}
    </span>

    <!-- Tooltip -->
    <div v-if="isHovered" class="ctrl-port__tooltip">
      {{ port.name }}
    </div>
  </div>
</template>

<style scoped>
/* ------------------------------------------------------------------ */
/* Layout wrapper                                                        */
/* ------------------------------------------------------------------ */
.ctrl-port {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  /* horizontal centering — parent sets `left` via inline style */
  padding: 0 4px;
  cursor: crosshair;
  z-index: 20;
}

/* Input on top: diamond centered on top edge, label below it (inside node) */
.ctrl-port--input  { top:    0; flex-direction: column-reverse; }
/* Output on bottom: diamond centered on bottom edge, label above it (inside node) */
.ctrl-port--output { bottom: 0; flex-direction: column; }

/* ------------------------------------------------------------------ */
/* Diamond                                                              */
/* ------------------------------------------------------------------ */
.ctrl-port__diamond {
  flex-shrink: 0;
  width:  10px;
  height: 10px;
  background: #fab387;
  border: 1.5px solid #1e1e2e;
  transform: rotate(45deg);
  box-shadow: 0 0 0 0 rgba(250, 179, 135, 0);
  transition:
    background  0.12s,
    box-shadow  0.12s,
    transform   0.12s;
}

/* Hover */
.ctrl-port--hovered .ctrl-port__diamond {
  background: #fecba0;
  box-shadow: 0 0 6px 2px rgba(250, 179, 135, 0.55);
  transform: rotate(45deg) scale(1.2);
}

/* Compatible drop target */
.ctrl-port--compatible .ctrl-port__diamond {
  background: #fecba0;
  box-shadow: 0 0 8px 3px rgba(250, 179, 135, 0.7);
  animation: ctrl-pulse 0.8s ease-in-out infinite alternate;
}

@keyframes ctrl-pulse {
  from { box-shadow: 0 0 4px 1px rgba(250, 179, 135, 0.5); }
  to   { box-shadow: 0 0 10px 4px rgba(250, 179, 135, 0.9); }
}

/* ------------------------------------------------------------------ */
/* Label                                                                */
/* ------------------------------------------------------------------ */
.ctrl-port__label {
  font-size: 9px;
  color: #a6adc8;
  white-space: nowrap;
  pointer-events: none;
  line-height: 1;
  text-align: center;
}

/* input:  label goes INSIDE the node = below the diamond (column-reverse → below = top visually) */
.ctrl-port__label--input  { margin-top:    3px; }
/* output: label goes INSIDE the node = above the diamond */
.ctrl-port__label--output { margin-bottom: 3px; }

.ctrl-port--hovered .ctrl-port__label { color: #cdd6f4; }

/* ------------------------------------------------------------------ */
/* Tooltip                                                              */
/* ------------------------------------------------------------------ */
.ctrl-port__tooltip {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  background: #181825;
  border: 1px solid #45475a;
  border-radius: 4px;
  padding: 3px 7px;
  font-size: 11px;
  color: #cdd6f4;
  pointer-events: none;
  z-index: 100;
}

.ctrl-port--input  .ctrl-port__tooltip { bottom: calc(100% + 4px); }
.ctrl-port--output .ctrl-port__tooltip { top:    calc(100% + 4px); }
</style>
