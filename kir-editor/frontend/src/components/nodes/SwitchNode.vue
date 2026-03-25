<script setup>
import { computed } from "vue";
import { useGraphStore } from "../../stores/graph.js";

const props = defineProps({ node: { type: Object, required: true } });
const emit = defineEmits(["add-case", "remove-case"]);
const graph = useGraphStore();

const caseOutputs = computed(() => props.node.controlPorts?.outputs ?? []);

function onCaseNameChange(port, e) {
  const liveNode = graph.nodes.get(props.node.id);
  const livePort = liveNode?.controlPorts.outputs.find((p) => p.id === port.id);
  if (livePort) livePort.name = e.target.value;
}
</script>

<template>
  <div class="switch-body">
    <div class="cases-list">
      <div v-for="port in caseOutputs" :key="port.id" class="case-row">
        <input
          class="case-input"
          :value="port.name"
          @change="onCaseNameChange(port, $event)"
          @pointerdown.stop
          @click.stop
          placeholder="case value"
        />
        <button
          class="rm"
          @click.stop="emit('remove-case', { portId: port.id })"
          @pointerdown.stop
        >
          x
        </button>
      </div>
    </div>
    <button class="add-btn" @click.stop="emit('add-case')" @pointerdown.stop>
      + add case
    </button>
  </div>
</template>

<style scoped>
.switch-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
}
.cases-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.case-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.case-input {
  flex: 1;
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid #45475a;
  background: #11111b;
  color: #cdd6f4;
  font-size: 10px;
  font-family: monospace;
  outline: none;
  min-width: 0;
}
.case-input:focus {
  border-color: #89b4fa;
}
.rm {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  border: 1px solid #45475a;
  background: transparent;
  color: #6c7086;
  font-size: 11px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  flex-shrink: 0;
}
.rm:hover {
  border-color: #f38ba8;
  color: #f38ba8;
}
.add-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px dashed #45475a;
  background: transparent;
  color: #6c7086;
  font-size: 10px;
  cursor: pointer;
  width: 100%;
  justify-content: center;
}
.add-btn:hover {
  border-color: #cba6f7;
  color: #cba6f7;
}
</style>
