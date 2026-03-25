<script setup>
import { ref, computed, inject } from "vue";
import { dtypeColor } from "../../utils/dtypeColors.js";

const props = defineProps({
  port: { type: Object, required: true },
  nodeId: { type: String, required: true },
  direction: {
    type: String,
    required: true,
    validator: (v) => ["input", "output"].includes(v),
  },
  portIndex: { type: Number, required: true },
  totalPorts: { type: Number, required: true },
});

const emit = defineEmits(["port-mousedown", "port-mouseup"]);
const isHovered = ref(false);
const draftWireType = inject("draftWireType", null);

const isCompatible = computed(() => {
  if (!draftWireType?.value) return false;
  return draftWireType.value === "data" && props.direction === "input";
});

const isOutput = computed(() => props.direction === "output");

function onMouseDown(e) {
  if (props.direction !== "output") return;
  e.stopPropagation();
  e.preventDefault();
  emit("port-mousedown", {
    nodeId: props.nodeId,
    portId: props.port.id,
    portType: "data",
    direction: props.direction,
  });
}

function onMouseUp(e) {
  if (props.direction !== "input") return;
  e.stopPropagation();
  emit("port-mouseup", {
    nodeId: props.nodeId,
    portId: props.port.id,
    portType: "data",
    direction: props.direction,
  });
}
</script>

<template>
  <div
    class="data-port"
    :class="[
      `data-port--${direction}`,
      {
        'data-port--hovered': isHovered,
        'data-port--compatible': isCompatible,
      },
    ]"
    :data-port-id="port.id"
    :data-node-id="nodeId"
    data-port-type="data"
    :data-port-dir="direction"
    @mousedown="onMouseDown"
    @mouseup="onMouseUp"
    @mouseenter="isHovered = true"
    @mouseleave="isHovered = false"
  >
    <div
      class="data-port__dot"
      :style="{ background: dtypeColor(port.dataType) }"
    />
    <span class="data-port__label">{{ port.name }}</span>
  </div>
</template>

<style scoped>
.data-port {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 4px;
  /* Parent sets top via inline style. Vertically center on that point. */
  transform: translateY(-50%);
  cursor: crosshair;
  z-index: 20;
  padding: 3px 0;
}

/* Input: circle on left border, label to the right */
.data-port--input {
  left: 0;
  transform: translateX(-50%) translateY(-50%);
  flex-direction: row;
}
/* Output: circle on right border, label to the left */
.data-port--output {
  right: 0;
  transform: translateX(50%) translateY(-50%);
  flex-direction: row-reverse;
}

.data-port__dot {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  /* color set dynamically via inline style; fallback for any edge case */
  background: #9399b2;
  border: 1.5px solid #1e1e2e;
  transition:
    background 0.12s,
    box-shadow 0.12s,
    transform 0.12s;
}

.data-port--hovered .data-port__dot {
  background: #b4d0ff;
  box-shadow: 0 0 6px 2px rgba(137, 180, 250, 0.55);
  transform: scale(1.2);
}
.data-port--compatible .data-port__dot {
  background: #b4d0ff;
  box-shadow: 0 0 8px 3px rgba(137, 180, 250, 0.7);
}

.data-port__label {
  font-size: 10px;
  color: #a6adc8;
  white-space: nowrap;
  pointer-events: none;
  line-height: 1;
}
.data-port--hovered .data-port__label {
  color: #cdd6f4;
}
</style>
