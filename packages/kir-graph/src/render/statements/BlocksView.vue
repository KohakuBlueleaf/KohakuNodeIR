<template>
  <div class="kg-blocks" @click="state.select?.(null)">
    <section class="kg-script">
      <div class="kg-block kg-hat" :class="model.name === 'main' ? 'kg-tone--event' : 'kg-tone--taaffeite'">
        <Icon :name="model.name === 'main' ? 'flag-filled' : 'function-math'" class="kg-block__icon" />
        <span class="kg-block__text">{{ model.name === "main" ? "when the program starts" : `define ${model.name}` }}</span>
        <template v-if="model.name === 'main'">
          <span v-for="u in model.doc.uses || []" :key="u.library" class="kg-block__label" :title="`@use ${u.library}`">{{ u.alias ? `${u.library} as ${u.alias}` : u.library }}</span>
        </template>
        <template v-else>
          <span v-for="p in model.graph.params || []" :key="p.name" class="kg-block__name" :title="p.type ? `${p.name}: ${p.type}` : p.name">{{ p.name }}</span>
          <template v-if="(model.graph.outputs || []).length">
            <span class="kg-block__text">→</span>
            <span v-for="o in model.graph.outputs" :key="o.name" class="kg-block__label">{{ o.name }}</span>
          </template>
        </template>
      </div>
      <div class="kg-stack">
        <Block v-for="(it, i) in items" :key="it.node.id + i" :item="it" :model="model" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from "vue"

import { statementTree } from "../../model/tree.js"
import Icon from "../Icon.vue"
import { useGraphState } from "../overlay.js"
import Block from "./Block.vue"

/**
 * Scratch-style blocks of one graph: a hat block, then its statements; C blocks
 * hold if / else, switch, loops, each, parallel, try / except and dataflow.
 * A graph's inputs node is its hat, so the stack starts after it.
 */
const props = defineProps({ model: { type: Object, required: true } })

const state = useGraphState()
const items = computed(() => statementTree(props.model).filter((it) => it.node.kind !== "inputs"))
</script>
