<script setup>
import { ref, computed, inject } from 'vue'

const props = defineProps({
  port: { type: Object, required: true },
  nodeId: { type: String, required: true },
  direction: { type: String, required: true, validator: v => ['input', 'output'].includes(v) },
  portIndex: { type: Number, required: true },
  totalPorts: { type: Number, required: true },
  label: { type: String, default: null },
})

const emit = defineEmits(['port-mousedown', 'port-mouseup'])
const isHovered = ref(false)
const draftWireType = inject('draftWireType', null)

const isCompatible = computed(() => {
  if (!draftWireType?.value) return false
  return draftWireType.value === 'control' && props.direction === 'input'
})

const displayLabel = computed(() => props.label || props.port.name)

function onMouseDown(e) {
  if (props.direction !== 'output') return
  e.stopPropagation()
  e.preventDefault()
  emit('port-mousedown', { nodeId: props.nodeId, portId: props.port.id, portType: 'control', direction: props.direction })
}

function onMouseUp(e) {
  if (props.direction !== 'input') return
  e.stopPropagation()
  emit('port-mouseup', { nodeId: props.nodeId, portId: props.port.id, portType: 'control', direction: props.direction })
}
</script>

<template>
  <div
    class="ctrl-port"
    :class="[
      `ctrl-port--${direction}`,
      { 'ctrl-port--hovered': isHovered, 'ctrl-port--compatible': isCompatible },
    ]"
    :data-port-id="port.id"
    :data-node-id="nodeId"
    data-port-type="control"
    :data-port-dir="direction"
    @mousedown="onMouseDown"
    @mouseup="onMouseUp"
    @mouseenter="isHovered = true"
    @mouseleave="isHovered = false"
  >
    <!-- Diamond on the edge -->
    <div class="ctrl-port__diamond" />
    <!-- Label inside the node -->
    <span v-if="displayLabel" class="ctrl-port__label">{{ displayLabel }}</span>
  </div>
</template>

<style scoped>
.ctrl-port {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: crosshair;
  z-index: 20;
  pointer-events: all;
}

/* Input: diamond sticks out the TOP of the ctrl row */
.ctrl-port--input {
  top: 0;
  transform: translateX(-50%) translateY(-50%);
}
/* Output: diamond sticks out the BOTTOM of the ctrl row */
.ctrl-port--output {
  bottom: 0;
  transform: translateX(-50%) translateY(50%);
}

/* Label positioning */
.ctrl-port--input .ctrl-port__label {
  order: 1; /* label below diamond for inputs */
}
.ctrl-port--output .ctrl-port__label {
  order: -1; /* label above diamond for outputs */
}

.ctrl-port__diamond {
  flex-shrink: 0;
  width: 10px; height: 10px;
  background: #fab387;
  border: 1.5px solid #1e1e2e;
  transform: rotate(45deg);
  transition: background 0.12s, box-shadow 0.12s;
}

.ctrl-port--hovered .ctrl-port__diamond {
  background: #fecba0;
  box-shadow: 0 0 6px 2px rgba(250, 179, 135, 0.55);
}
.ctrl-port--compatible .ctrl-port__diamond {
  background: #fecba0;
  box-shadow: 0 0 8px 3px rgba(250, 179, 135, 0.7);
}

.ctrl-port__label {
  font-size: 8px;
  color: #a6adc8;
  white-space: nowrap;
  pointer-events: none;
  line-height: 1;
  margin: 2px 0;
}

.ctrl-port--hovered .ctrl-port__label { color: #cdd6f4; }
</style>
