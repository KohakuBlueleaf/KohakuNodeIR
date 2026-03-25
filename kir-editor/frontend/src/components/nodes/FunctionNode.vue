<script setup>
import { computed } from 'vue'
import { useNodeRegistryStore } from '../../stores/nodeRegistry.js'
import { useGraphStore } from '../../stores/graph.js'

const props = defineProps({ node: { type: Object, required: true } })
const emit = defineEmits(['update:property'])

const registry = useNodeRegistryStore()
const graph = useGraphStore()

const nodeDef = computed(() => registry.getNodeType(props.node.type))
const propertyDefs = computed(() => {
  const def = nodeDef.value
  if (!def) return []
  // properties can be an array of {name, widget, default, options}
  if (Array.isArray(def.properties)) return def.properties
  return []
})

function getPropValue(propName) {
  return props.node.properties?.[propName]
}

function setPropValue(propName, value) {
  const liveNode = graph.nodes.get(props.node.id)
  if (liveNode) {
    liveNode.properties[propName] = value
  }
}

function getSelectChoices(prop) {
  const raw = prop.options?.choices ?? ''
  return raw.split(',').map(s => s.trim()).filter(Boolean)
}
</script>

<template>
  <div class="fn-body">
    <div v-if="node.properties?.code" class="code-badge">has code</div>

    <!-- Property widgets -->
    <div v-for="prop in propertyDefs" :key="prop.name" class="fn-prop">
      <label class="fn-prop-label">{{ prop.name }}</label>

      <!-- string -->
      <input
        v-if="prop.widget === 'string'"
        class="fn-prop-input"
        type="text"
        :value="getPropValue(prop.name) ?? prop.default ?? ''"
        @change="setPropValue(prop.name, $event.target.value)"
        @pointerdown.stop @click.stop
      />

      <!-- number -->
      <input
        v-else-if="prop.widget === 'number'"
        class="fn-prop-input"
        type="number"
        :value="getPropValue(prop.name) ?? prop.default ?? 0"
        @change="setPropValue(prop.name, parseFloat($event.target.value) || 0)"
        @pointerdown.stop @click.stop
      />

      <!-- boolean -->
      <label v-else-if="prop.widget === 'boolean'" class="fn-prop-bool">
        <input
          type="checkbox"
          :checked="!!(getPropValue(prop.name) ?? prop.default)"
          @change="setPropValue(prop.name, $event.target.checked)"
          @pointerdown.stop @click.stop
        />
        {{ getPropValue(prop.name) ?? prop.default ? 'true' : 'false' }}
      </label>

      <!-- select -->
      <select
        v-else-if="prop.widget === 'select'"
        class="fn-prop-select"
        :value="getPropValue(prop.name) ?? prop.default ?? ''"
        @change="setPropValue(prop.name, $event.target.value)"
        @pointerdown.stop @click.stop
      >
        <option v-for="opt in getSelectChoices(prop)" :key="opt" :value="opt">{{ opt }}</option>
      </select>

      <!-- slider -->
      <div v-else-if="prop.widget === 'slider'" class="fn-prop-slider-wrap">
        <input
          class="fn-prop-slider"
          type="range"
          :min="prop.options?.min ?? 0"
          :max="prop.options?.max ?? 100"
          :step="prop.options?.step ?? 1"
          :value="getPropValue(prop.name) ?? prop.default ?? 0"
          @input="setPropValue(prop.name, parseFloat($event.target.value))"
          @pointerdown.stop @click.stop
        />
        <span class="fn-prop-slider-val">{{ getPropValue(prop.name) ?? prop.default ?? 0 }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fn-body { font-size: 11px; }
.code-badge { display: inline-flex; align-items: center; gap: 4px; padding: 1px 6px; border-radius: 3px; background: rgba(137,180,250,0.12); border: 1px solid rgba(137,180,250,0.25); color: #89b4fa; font-size: 10px; font-weight: 600; width: fit-content; }

.fn-prop { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.fn-prop-label { font-size: 9px; font-weight: 700; text-transform: uppercase; color: #6c7086; flex-shrink: 0; min-width: 36px; }
.fn-prop-input { flex: 1; padding: 2px 5px; border-radius: 3px; border: 1px solid #45475a; background: #11111b; color: #cdd6f4; font-size: 10px; font-family: monospace; outline: none; min-width: 0; }
.fn-prop-input:focus { border-color: #89b4fa; }
.fn-prop-bool { display: flex; align-items: center; gap: 5px; cursor: pointer; font-family: monospace; color: #fab387; font-size: 10px; }
.fn-prop-bool input { accent-color: #89b4fa; width: 12px; height: 12px; cursor: pointer; }
.fn-prop-select { flex: 1; background: #11111b; border: 1px solid #45475a; border-radius: 3px; color: #cdd6f4; font-size: 10px; padding: 2px 4px; outline: none; min-width: 0; }
.fn-prop-select:focus { border-color: #89b4fa; }
.fn-prop-slider-wrap { display: flex; align-items: center; gap: 4px; flex: 1; }
.fn-prop-slider { flex: 1; accent-color: #89b4fa; height: 14px; min-width: 0; }
.fn-prop-slider-val { font-size: 9px; font-family: monospace; color: #a6adc8; min-width: 24px; text-align: right; }
</style>
