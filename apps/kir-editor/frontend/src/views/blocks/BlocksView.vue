<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="kir-viewbar">
      <span class="kir-viewbar__title"><span class="i-carbon-blockchain" />Blocks</span>
      <span class="text-[10.5px] text-warm-500">drag blocks to reorder or nest · click a slot to type · drag a variable into a slot</span>
    </div>
    <div class="sb-vars">
      <span class="section-title mr-1">variables</span>
      <span v-for="v in vars" :key="v" class="sb-reporter sb-reporter--palette" draggable="true" :title="`drag into a slot to read ${v}`" @dragstart="dragVar($event, v)">{{ v }}</span>
      <span class="sb-block sb-cmd sb-cat--var sb-palette-cmd" draggable="true" title="drag into a stack: set a variable" @dragstart="dragSet">
        <span class="sb-text">set</span><span class="sb-name">x</span><span class="sb-text">to</span><span class="sb-slot sb-slot--round">0</span>
      </span>
    </div>
    <div class="flex-1 overflow-auto sb-canvas" data-test="blocks-canvas">
      <div v-if="!ctx.tree.value" class="p-4 text-sm text-warm-500">No program yet.</div>
      <div v-else class="sb-scripts">
        <section class="sb-script" data-script="main">
          <div class="sb-block sb-hat sb-cat--event">
            <span class="i-carbon-flag-filled text-sm" />
            <span class="sb-text">when the program starts</span>
            <span v-for="u in ctx.tree.value.uses" :key="u.library" class="sb-label" :title="`@use ${u.library}`">{{ u.alias ? `${u.library} as ${u.alias}` : u.library }}</span>
          </div>
          <ScratchStack :list="ctx.tree.value.body" />
        </section>
        <section v-for="(it, i) in ctx.tree.value.head" :key="`h${i}`" class="sb-script" :data-script="it.t === 'def' ? it.s.name : 'typehints'">
          <template v-if="it.t === 'def'">
            <div class="sb-block sb-hat sb-hat--define sb-cat--def">
              <span class="sb-text">define</span>
              <span class="sb-text sb-text--name">{{ it.s.name }}</span>
              <span v-for="p in it.s.params" :key="p.name" class="sb-reporter sb-reporter--param" draggable="true" :title="paramTitle(p)" @dragstart="dragVar($event, p.name)">{{ p.name }}</span>
              <template v-if="it.s.outputs.length">
                <span class="sb-text">→</span>
                <span v-for="o in it.s.outputs" :key="o.name" class="sb-label" :title="o.type ? `${o.name}: ${o.type}` : o.name">{{ o.name }}</span>
              </template>
            </div>
            <ScratchStack :list="it.body" />
          </template>
          <ScratchBlock v-else :item="it" :list="ctx.tree.value.head" />
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"

import { formatLiteral } from "@/graph/literal"
import { NODE_MIME, VAR_MIME } from "@/program/edit"
import { variables } from "@/program/structure"
import { provideStatementTree } from "@/program/useStatementTree"
import ScratchBlock from "@/views/blocks/ScratchBlock.vue"
import ScratchStack from "@/views/blocks/ScratchStack.vue"

/**
 * Scratch-style blocks: a hat for the program (and one per @def), command
 * blocks with inline slots, C blocks for if / else, switch, loops, each,
 * parallel, try / except, labelled blocks and @dataflow.
 */
const ctx = provideStatementTree()
const vars = computed(() => (ctx.tree.value ? variables(ctx.tree.value) : []))

function paramTitle(p) {
  return `${p.name}${p.type ? `: ${p.type}` : ""}${p.default ? ` = ${"lit" in p.default ? formatLiteral(p.default.lit) : p.default.name}` : ""}`
}

function dragVar(event, name) {
  event.dataTransfer.setData(VAR_MIME, name)
  event.dataTransfer.effectAllowed = "copy"
}

function dragSet(event) {
  event.dataTransfer.setData(NODE_MIME, JSON.stringify({ kind: "assign" }))
  event.dataTransfer.effectAllowed = "copy"
}

/** Palette click: append the statement to the program's main stack. */
function addAtCenter(spec) {
  if (ctx.tree.value) ctx.insert(spec, ctx.tree.value.body, ctx.tree.value.body.length)
}

defineExpose({ addAtCenter })
</script>
