<script setup>
/**
 * DataPort — circular port on the left (input) or right (output) edge of a node.
 *
 * Positioning: the port circle sits exactly on the node edge.
 *   - Input:  left edge  → translateX(-50%)
 *   - Output: right edge → translateX(50%)
 *
 * Vertical placement is handled by the parent (BaseNode) via an inline `top`
 * style passed down through the `style` attribute, so the port itself only
 * needs to know its horizontal side.
 *
 * Wire drawing:
 *   - Mousedown on an OUTPUT port → emits 'port-mousedown' upward to BaseNode
 *   - Mouseup   on an INPUT  port → emits 'port-mouseup'   upward to BaseNode
 *
 * The parent BaseNode forwards these to the editor store (startDraftWire /
 * endDraftWire).  The port component stays store-agnostic.
 */

import { ref, computed, inject } from 'vue'

const props = defineProps({
  /** Port data object from node.dataPorts.inputs[i] / .outputs[i] */
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
  /** Total count of ports on this side (used for evenly distributing) */
  totalPorts: {
    type: Number,
    required: true,
  },
})

const emit = defineEmits(['port-mousedown', 'port-mouseup'])

// ---- hover / active state ----
const isHovered = ref(false)

// ---- draft-wire compatibility highlight ----
// Injected from BaseNode so ports can react to the active draft wire type
const draftWireType = inject('draftWireType', null)   // Ref<string|null>
const draftWireDir  = inject('draftWireDir',  null)   // Ref<'input'|'output'|null>

const isCompatible = computed(() => {
  if (!draftWireType?.value) return false
  // A data-wire draft can land only on an input port (outputs start drags)
  return draftWireType.value === 'data' && props.direction === 'input'
})

// ---- computed classes / styles ----
const isOutput = computed(() => props.direction === 'output')

const portStyle = computed(() => ({
  // Center the circle on the node edge
  transform: isOutput.value ? 'translateX(50%)' : 'translateX(-50%)',
}))

// ---- interaction handlers ----
function onMouseDown(e) {
  if (props.direction !== 'output') return
  e.stopPropagation()
  e.preventDefault()
  emit('port-mousedown', {
    nodeId:   props.nodeId,
    portId:   props.port.id,
    portType: 'data',
    direction: props.direction,
    event:    e,
  })
}

function onMouseUp(e) {
  if (props.direction !== 'input') return
  e.stopPropagation()
  emit('port-mouseup', {
    nodeId:   props.nodeId,
    portId:   props.port.id,
    portType: 'data',
    direction: props.direction,
    event:    e,
  })
}

function onMouseEnter() { isHovered.value = true  }
function onMouseLeave() { isHovered.value = false }
</script>

<template>
  <div
    class="data-port"
    :class="[
      `data-port--${direction}`,
      { 'data-port--hovered':    isHovered    },
      { 'data-port--compatible': isCompatible },
    ]"
    :style="portStyle"
    :data-port-id="port.id"
    :data-node-id="nodeId"
    data-port-type="data"
    :data-port-dir="direction"
    @mousedown="onMouseDown"
    @mouseup="onMouseUp"
    @mouseenter="onMouseEnter"
    @mouseleave="onMouseLeave"
  >
    <!-- The circle dot -->
    <div class="data-port__dot" />

      <!-- Tooltip shown on hover -->
    <div v-if="isHovered" class="data-port__tooltip">
      {{ port.name }}<template v-if="port.dataType"> · {{ port.dataType }}</template>
      <template v-if="port.defaultValue !== undefined && direction === 'input'">
        <br>default: {{ port.defaultValue }}
      </template>
    </div>
  </div>
</template>

<style scoped>
/* ------------------------------------------------------------------ */
/* Layout wrapper                                                        */
/* ------------------------------------------------------------------ */
.data-port {
  position: absolute;
  display: flex;
  align-items: center;
  /* vertically centered — parent sets `top` via inline style */
  translate: 0 -50%;
  /* pointer-events extend slightly beyond the circle for easier targeting */
  padding: 4px 0;
  cursor: crosshair;
  z-index: 20;
}

.data-port--input  { left: 0;  flex-direction: row; }
.data-port--output { right: 0; flex-direction: row-reverse; }

/* ------------------------------------------------------------------ */
/* Circle                                                               */
/* ------------------------------------------------------------------ */
.data-port__dot {
  flex-shrink: 0;
  width:  10px;
  height: 10px;
  border-radius: 50%;
  background: #89b4fa;
  border: 1.5px solid #1e1e2e;
  box-shadow: 0 0 0 0 rgba(137, 180, 250, 0);
  transition:
    background 0.12s,
    box-shadow 0.12s,
    transform  0.12s;
}

/* Hover — brighter fill + glow */
.data-port--hovered .data-port__dot {
  background: #b4d0ff;
  box-shadow: 0 0 6px 2px rgba(137, 180, 250, 0.55);
  transform: scale(1.2);
}

/* Compatible drop target — pulse glow while a draft wire is active */
.data-port--compatible .data-port__dot {
  background: #b4d0ff;
  box-shadow: 0 0 8px 3px rgba(137, 180, 250, 0.7);
  animation: port-pulse 0.8s ease-in-out infinite alternate;
}

@keyframes port-pulse {
  from { box-shadow: 0 0 4px 1px rgba(137, 180, 250, 0.5); }
  to   { box-shadow: 0 0 10px 4px rgba(137, 180, 250, 0.9); }
}

/* ------------------------------------------------------------------ */
/* Label                                                                */
/* ------------------------------------------------------------------ */
.data-port__label {
  font-size: 11px;
  color: #a6adc8;
  white-space: nowrap;
  pointer-events: none;
  line-height: 1;
  /* gap from the dot */
}

.data-port__label--input  { margin-left:  5px; }
.data-port__label--output { margin-right: 5px; }

.data-port--hovered .data-port__label { color: #cdd6f4; }

.data-port__type {
  font-size: 9px;
  color: #6c7086;
  margin-left: 2px;
}

/* ------------------------------------------------------------------ */
/* Tooltip                                                              */
/* ------------------------------------------------------------------ */
.data-port__tooltip {
  position: absolute;
  /* float above the port, offset outward from the node edge */
  top: 50%;
  transform: translateY(-50%);
  white-space: nowrap;
  background: #181825;
  border: 1px solid #45475a;
  border-radius: 4px;
  padding: 3px 7px;
  font-size: 11px;
  color: #cdd6f4;
  pointer-events: none;
  z-index: 100;
  line-height: 1.5;
}

.data-port--input  .data-port__tooltip { left:  calc(100% + 6px); }
.data-port--output .data-port__tooltip { right: calc(100% + 6px); }
</style>
