<template>
  <aside class="h-full flex flex-col bg-warm-100 dark:bg-warm-950 border-r border-warm-200 dark:border-warm-800 min-w-0">
    <div class="panel-head">
      <span class="i-carbon-add-alt text-iolite" />
      <span class="text-xs font-semibold text-warm-700 dark:text-warm-200">Palette</span>
      <span class="flex-1" />
      <button class="btn-icon" title="Reload signatures from the backend" @click="lib.load()"><span class="i-carbon-renew text-sm" /></button>
    </div>
    <div class="p-2 shrink-0">
      <input v-model="query" class="input-field" placeholder="filter nodes…" />
    </div>
    <div class="flex-1 overflow-y-auto px-2 pb-3 flex flex-col gap-3">
      <section>
        <div class="section-title px-1 mb-1">Builtins</div>
        <div class="grid grid-cols-2 gap-1">
          <button v-for="b in builtins" :key="b.kind" class="kir-pal-item" draggable="true" :title="b.hint" @dragstart="drag($event, { kind: b.kind })" @click="emit('add', { kind: b.kind })">
            <span :class="b.icon" class="text-iolite dark:text-iolite-light" />
            <span class="truncate">{{ b.kind }}</span>
          </button>
        </div>
      </section>

      <section v-if="defs.length">
        <div class="section-title px-1 mb-1">Subgraphs (@def)</div>
        <button v-for="d in defs" :key="d.name" class="kir-pal-item w-full" draggable="true" :title="d.sigText" @dragstart="drag($event, d.spec)" @click="emit('add', d.spec)">
          <span class="i-carbon-function-math text-taaffeite" />
          <span class="truncate">{{ d.name }}</span>
        </button>
      </section>

      <section v-for="l in libraries" :key="l.library">
        <div class="w-full flex items-center gap-1 px-1 mb-1 cursor-pointer select-none" @click="toggle(l.library)">
          <span :class="collapsed[l.library] ? 'i-carbon-chevron-right' : 'i-carbon-chevron-down'" class="text-[10px] text-warm-500" />
          <span class="section-title">{{ l.library }}</span>
          <span class="flex-1" />
          <span v-if="l.runnable" class="chip-aqua" title="has implementations: the run button can execute it">runs</span>
          <span v-else class="chip-warm" :title="`signatures only (${l.source})`">sig</span>
          <button v-if="l.source === 'loaded file'" class="btn-icon !w-5 !h-5" title="Unload" @click.stop="lib.removeUploaded(l.library)"><span class="i-carbon-close text-xs" /></button>
        </div>
        <label v-if="l.library === 'demo'" class="flex items-center gap-1.5 px-1 mb-1 text-[11px] text-warm-600 dark:text-warm-400" title="Give demo to every program unaliased. Turn off when a loaded library shares node names with it (E011).">
          <input v-model="lib.useDemo" type="checkbox" class="accent-iolite" @change="docStore.syncTextToGraph()" />
          in scope without @use
        </label>
        <div v-if="!collapsed[l.library]" class="flex flex-col gap-0.5">
          <button v-for="n in l.shown" :key="n.name" class="kir-pal-item w-full" draggable="true" :title="sigText(n)" @dragstart="drag($event, callSpec(l, n))" @click="emit('add', callSpec(l, n))">
            <span class="i-carbon-function text-sapphire dark:text-sapphire-light shrink-0" />
            <span class="truncate">{{ n.name }}</span>
            <span class="flex-1" />
            <span class="text-[10px] text-warm-400 truncate">{{ n.inputs.length }}→{{ n.outputs.length }}</span>
          </button>
          <div v-if="!l.shown.length" class="px-2 text-[11px] text-warm-400">no match</div>
        </div>
      </section>

      <div v-if="lib.error" class="chip-coral !rounded-md !whitespace-normal !leading-snug p-2">backend: {{ lib.error }}</div>
    </div>
  </aside>
</template>

<script setup>
import { computed, reactive, ref } from "vue"

import { useDocumentStore } from "@/stores/document"
import { useLibraryStore } from "@/stores/library"

const emit = defineEmits(["add"])
const DRAG_MIME = "application/x-kir-node"

const lib = useLibraryStore()
const docStore = useDocumentStore()
const query = ref("")
const collapsed = reactive({ "kir.std": true })

const BUILTINS = [
  { kind: "assign", icon: "i-carbon-assignment", hint: "name = value: a command on the control chain" },
  { kind: "value", icon: "i-carbon-character-whole-number", hint: "a literal as a node (graph views)" },
  { kind: "get", icon: "i-carbon-download", hint: "read a variable (graph views)" },
  { kind: "set", icon: "i-carbon-upload", hint: "name the output wired into it (graph views)" },
  { kind: "branch", icon: "i-carbon-flow-connection", hint: "(cond)branch(`t`, `f`)" },
  { kind: "switch", icon: "i-carbon-tree-view-alt", hint: "(value)switch(1=>`a`, _=>`b`)" },
  { kind: "merge", icon: "i-carbon-direction-merge", hint: "join control paths; with a label it is a loop entry (in the statement views: a loop)" },
  { kind: "each", icon: "i-carbon-repeat", hint: "(items)each(item, index, `body`)" },
  { kind: "parallel", icon: "i-carbon-split", hint: "()parallel(`a`, `b`)" },
  { kind: "try", icon: "i-carbon-warning-alt", hint: "@try: … @except err: …" },
]

const match = (s) => !query.value || s.toLowerCase().includes(query.value.toLowerCase())

const builtins = computed(() => BUILTINS.filter((b) => match(b.kind)))

const defs = computed(() =>
  docStore.doc.graphs
    .filter((g) => g.name !== "main" && match(g.name))
    .map((g) => {
      const sig = {
        name: g.name,
        inputs: (g.params || []).map((p) => ({ name: p.name, ...(p.type ? { type: p.type } : {}), ...("default" in p ? { default: p.default } : {}) })),
        outputs: (g.outputs || []).map((o) => ({ name: o.name, ...(o.type ? { type: o.type } : {}) })),
      }
      return { name: g.name, sigText: sigText(sig), spec: { kind: "call", name: g.name, sig } }
    }),
)

const libraries = computed(() =>
  lib.libraries.map((l) => ({ ...l, shown: (l.nodes || []).filter((n) => match(n.name)) })),
)

function toggle(name) {
  collapsed[name] = !collapsed[name]
}

function sigText(n) {
  const ins = n.inputs.map((p) => `${p.name}${p.type ? `: ${p.type}` : ""}${"default" in p ? ` = ${JSON.stringify(p.default)}` : ""}`)
  const outs = n.outputs.map((p) => `${p.name}${p.type ? `: ${p.type}` : ""}`)
  return `(${ins.join(", ")})${n.name}(${outs.join(", ")})${n.doc ? `\n\n${n.doc}` : ""}`
}

function callSpec(l, n) {
  const { name, use } = lib.callName(l.library, n.name, docStore.doc)
  return { kind: "call", name, sig: n, ...(use ? { use } : {}) }
}

function drag(event, spec) {
  event.dataTransfer.setData(DRAG_MIME, JSON.stringify(spec))
  event.dataTransfer.effectAllowed = "copy"
}
</script>

<style>
.kir-pal-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  height: 1.75rem;
  padding: 0 0.5rem;
  border-radius: 0.4rem;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--color-text);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  cursor: grab;
  text-align: left;
  min-width: 0;
}
.kir-pal-item:hover {
  border-color: var(--kt-color-iolite);
}
</style>
