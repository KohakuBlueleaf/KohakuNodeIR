<template>
  <aside data-test="inspector" class="h-full flex flex-col bg-warm-100 dark:bg-warm-950 border-l border-warm-200 dark:border-warm-800 min-w-0">
    <div class="panel-head">
      <span class="i-carbon-settings-adjust text-iolite" />
      <span class="text-xs font-semibold text-warm-700 dark:text-warm-200">Inspector</span>
      <span class="flex-1" />
      <button v-if="node" class="btn-icon" title="Delete node (Del)" @click="docStore.removeNodes([node.id])"><span class="i-carbon-trash-can text-sm text-coral" /></button>
    </div>

    <div v-if="!node" class="p-3 text-xs text-warm-500 leading-relaxed">
      <p>Select a node to see its ports, types, hints and meta.</p>
      <p class="mt-2">In the node and flowchart views, drag from an output port to an input port of the same kind (control or data) to wire them; Del removes the selection. The blocks and sequence views edit statements in place.</p>
      <div class="mt-4 section-title">Graph · {{ docStore.graphName }}</div>
      <div class="mt-1 font-mono text-[11px]">{{ docStore.graph?.nodes.length ?? 0 }} nodes · {{ docStore.graph?.edges.length ?? 0 }} edges</div>
      <template v-if="docStore.graph?.params">
        <div class="mt-3 section-title">@def signature</div>
        <div class="mt-1 font-mono text-[11px] break-all">({{ docStore.graph.params.map(paramText).join(", ") }}){{ docStore.graphName }}({{ (docStore.graph.outputs || []).map(paramText).join(", ") }})</div>
      </template>
    </div>

    <div v-else class="flex-1 overflow-y-auto p-3 flex flex-col gap-3 text-xs">
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="chip-iolite">{{ node.kind }}</span>
        <span class="font-mono text-warm-600 dark:text-warm-300 break-all">{{ node.id }}</span>
      </div>

      <template v-if="node.kind === 'call'">
        <div>
          <div class="font-mono text-sm font-semibold text-warm-800 dark:text-warm-100 break-all">{{ node.name }}</div>
          <div v-if="resolved?.kind === 'node'" class="mt-0.5 text-[11px] text-warm-500">from <span class="font-mono">{{ resolved.library }}</span><span v-if="resolved.sig.flags?.ordered"> · ordered</span></div>
          <div v-else-if="resolved?.kind === 'def'" class="mt-0.5 text-[11px] text-taaffeite">a @def in this program</div>
          <div v-else class="mt-0.5 text-[11px] text-coral">unresolved: no library or @def has this node</div>
          <p v-if="resolved?.sig?.doc" class="mt-1.5 text-[11px] text-warm-600 dark:text-warm-400 whitespace-pre-wrap">{{ resolved.sig.doc }}</p>
          <button v-if="resolved?.kind === 'def'" class="btn-ghost mt-1 !px-0 text-iolite" @click="docStore.selectGraph(node.name)"><span class="i-carbon-launch" />open {{ node.name }}</button>
        </div>
      </template>

      <!-- Kind-specific properties -->
      <section v-if="node.kind === 'value'" class="flex flex-col gap-2">
        <InspectorField label="literal" :value="formatLiteral(node.props.value)" :commit="(t) => edit((n) => (n.props.value = parseLiteral(t)))" />
        <div class="text-[11px] text-warm-500">A wire from a literal is the same as writing it in the input box it feeds.</div>
      </section>
      <section v-else-if="node.kind === 'get'" class="flex flex-col gap-2">
        <InspectorField label="reads variable" :value="node.props.name" :commit="(t) => edit((n) => (n.props.name = ident(t)))" />
      </section>
      <section v-else-if="node.kind === 'set'" class="flex flex-col gap-2">
        <InspectorField label="writes variable" :value="node.props.name" :commit="(t) => edit((n) => (n.props.name = ident(t)))" />
        <div class="text-[11px] text-warm-500">Names the output wired into it: the write happens when that node runs.</div>
      </section>
      <section v-else-if="node.kind === 'assign'" class="flex flex-col gap-2">
        <InspectorField v-if="!wiredFrom('value')" label="value (literal)" :value="'value' in node.inputs[0] ? formatLiteral(node.inputs[0].value) : ''" :commit="(t) => edit(setInputValue(0, t))" />
        <InspectorField label="variable (empty: named by a set node)" :value="node.outputs[0].var || ''" :commit="(t) => edit((n) => setVar(n.outputs[0], t))" />
        <InspectorField label="type (optional)" :value="node.outputs[0].type || ''" :commit="(t) => edit((n) => setType(n.outputs[0], t))" />
      </section>
      <section v-else-if="node.kind === 'branch'" class="grid grid-cols-2 gap-2">
        <InspectorField label="true → namespace" :value="node.props.labels.true" :commit="(t) => edit((n) => (n.props.labels.true = ident(t)))" />
        <InspectorField label="false → namespace" :value="node.props.labels.false" :commit="(t) => edit((n) => (n.props.labels.false = ident(t)))" />
      </section>
      <section v-else-if="node.kind === 'switch'" class="flex flex-col gap-2">
        <div v-for="(port, i) in node.ctrl_out" :key="port" class="grid grid-cols-2 gap-2">
          <InspectorField v-if="port !== 'default'" :label="`case ${i}`" :value="formatLiteral(node.props.cases[i])" :commit="(t) => edit((n) => (n.props.cases[i] = parseLiteral(t)))" />
          <div v-else class="text-[11px] text-warm-500 self-end pb-1">default (_)</div>
          <InspectorField label="→ namespace" :value="node.props.labels[port]" :commit="(t) => edit((n) => (n.props.labels[port] = ident(t)))" />
        </div>
        <div class="flex gap-1">
          <button class="btn-ghost" @click="docStore.addArm()"><span class="i-carbon-add" />case</button>
          <button class="btn-ghost" @click="docStore.removeArm()"><span class="i-carbon-subtract" />case</button>
          <button class="btn-ghost" @click="docStore.toggleDefault()">{{ node.ctrl_out.includes("default") ? "drop default" : "add default" }}</button>
        </div>
      </section>
      <section v-else-if="node.kind === 'merge'" class="flex flex-col gap-2">
        <InspectorField label="loop label (empty: a plain join)" :value="node.props?.label || ''" :commit="(t) => edit(setMergeLabel(t))" />
        <div class="text-[11px] text-warm-500">{{ node.ctrl_in.length }} incoming paths; a free slot on top takes one more.</div>
      </section>
      <section v-else-if="['each', 'collect'].includes(node.kind)" class="grid grid-cols-2 gap-2">
        <InspectorField label="body namespace" :value="node.props.label" :commit="(t) => edit((n) => (n.props.label = ident(t)))" />
        <InspectorField label="item name" :value="node.props.item || ''" :commit="(t) => edit(setEachName('item', t))" />
        <InspectorField label="index name" :value="node.props.index || ''" :commit="(t) => edit(setEachName('index', t))" />
        <label class="flex items-center gap-1.5 text-[11px] text-warm-600 dark:text-warm-400 self-end pb-1"><input type="checkbox" class="accent-iolite" :checked="node.props.has_index" @change="edit((n) => (n.props.has_index = !n.props.has_index))" />bind index</label>
        <InspectorField v-if="node.kind === 'collect'" label="result list (after completion)" :value="node.props.target" :commit="(t) => edit(setCollectTarget(t))" />
      </section>
      <section v-else-if="node.kind === 'parallel'" class="flex flex-col gap-2">
        <InspectorField v-for="port in node.ctrl_out" :key="port" :label="`${port} → namespace`" :value="node.props.labels[port]" :commit="(t) => edit((n) => (n.props.labels[port] = ident(t)))" />
        <div class="flex gap-1">
          <button class="btn-ghost" @click="docStore.addArm()"><span class="i-carbon-add" />arm</button>
          <button class="btn-ghost" @click="docStore.removeArm()"><span class="i-carbon-subtract" />arm</button>
        </div>
      </section>
      <section v-else-if="node.kind === 'try'" class="flex flex-col gap-2">
        <InspectorField label="@except name (empty: none)" :value="node.props.error_name || ''" :commit="(t) => edit(setErrorName(t))" />
      </section>

      <!-- Ports -->
      <section v-if="node.inputs?.length && !['value', 'set', 'assign'].includes(node.kind)">
        <div class="section-title mb-1">Inputs</div>
        <div class="flex flex-col gap-1.5">
          <div v-for="(p, i) in node.inputs" :key="p.port" class="flex flex-col gap-0.5">
            <div class="flex items-center gap-1.5 font-mono">
              <span class="inline-block w-2 h-2 rounded-full shrink-0" :style="{ background: typeColor(p.type) }" />
              <span class="text-warm-800 dark:text-warm-100">{{ p.port }}</span>
              <span class="text-warm-500">{{ p.type || "_" }}</span>
              <span v-if="p.keyword" class="chip-warm">kw</span>
              <span v-if="p.deferred === 'body_end'" class="chip-warm" title="Read after each normal body completion, not at loop entry">body end</span>
              <span class="flex-1" />
              <span v-if="wiredFrom(p.port)" class="text-iolite dark:text-iolite-light truncate" :title="wiredFrom(p.port)">← {{ wiredFrom(p.port) }}</span>
            </div>
            <InspectorField v-if="!wiredFrom(p.port)" :value="'value' in p ? formatLiteral(p.value) : ''" placeholder="literal, or wire it" :commit="(t) => edit(setInputValue(i, t))" />
          </div>
        </div>
      </section>

      <section v-if="node.outputs?.length && !['value', 'get', 'assign'].includes(node.kind)">
        <div class="section-title mb-1">Outputs</div>
        <div class="flex flex-col gap-1.5">
          <div v-for="(p, i) in node.outputs" :key="p.port" class="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-0.5">
            <div class="flex items-center gap-1.5 font-mono">
              <span class="inline-block w-2 h-2 rounded-full shrink-0" :style="{ background: typeColor(p.type) }" />
              <span class="text-warm-800 dark:text-warm-100">{{ p.port }}</span>
              <span class="text-warm-500">{{ p.type || "_" }}</span>
            </div>
            <InspectorField v-if="node.kind === 'call'" :value="p.var ?? ''" placeholder="name (empty: _)" :commit="(t) => edit(setOutputVar(i, t))" />
            <span v-else class="font-mono text-warm-600 dark:text-warm-300">{{ p.var }}</span>
          </div>
        </div>
      </section>

      <section v-if="node.ctrl_in?.length || node.ctrl_out?.length">
        <div class="section-title mb-1">Control</div>
        <div class="font-mono text-[11px] text-warm-600 dark:text-warm-300">in: {{ (node.ctrl_in || []).join(", ") || "—" }} · out: {{ (node.ctrl_out || []).join(", ") || "—" }}</div>
      </section>

      <section>
        <div class="section-title mb-1">@hint</div>
        <InspectorField :value="pairsText(node.hints)" placeholder="key=value …" :commit="(t) => edit((n) => setPairs(n, 'hints', t))" />
      </section>
      <section v-if="node.meta && Object.keys(node.meta).length">
        <div class="section-title mb-1">@meta</div>
        <div class="font-mono text-[11px] text-warm-600 dark:text-warm-300 break-all">{{ pairsText(node.meta) }}</div>
      </section>
    </div>
  </aside>
</template>

<script setup>
import { computed } from "vue"

import InspectorField from "@/components/panels/inspector/InspectorField.vue"
import { formatLiteral, parseLiteral, typeColor } from "@kohaku/kir-graph"

import { useDocumentStore } from "@/stores/document"
import { useLibraryStore } from "@/stores/library"

const docStore = useDocumentStore()
const lib = useLibraryStore()

const node = computed(() => docStore.selected)
const resolved = computed(() => (node.value?.kind === "call" ? lib.resolveCall(node.value.name, docStore.doc) : null))

const edit = (fn) => docStore.updateSelected(fn)

function ident(text) {
  const t = text.trim()
  if (!/^[A-Za-z_]\w*$/.test(t)) throw new Error("not an identifier")
  if (t.includes("__")) throw new Error("names with __ are reserved")
  return t
}

function paramText(p) {
  return `${p.name}${p.type ? `: ${p.type}` : ""}${"default" in p ? ` = ${formatLiteral(p.default)}` : ""}`
}

function wiredFrom(port) {
  const n = node.value
  const e = docStore.graph.edges.find((x) => x.kind === "data" && x.to.node === n.id && x.to.port === port)
  return e ? `${e.from.node}.${e.from.port}` : ""
}

function setType(port, text) {
  const t = text.trim()
  if (t) port.type = t
  else delete port.type
}

const setInputValue = (i, text) => (n) => {
  if (!text.trim()) delete n.inputs[i].value
  else n.inputs[i].value = parseLiteral(text)
}

const setOutputVar = (i, text) => (n) => {
  n.outputs[i].var = text.trim() ? ident(text) : null
}

function setVar(port, text) {
  const t = text.trim()
  if (t) port.var = ident(t)
  else delete port.var
}

const setMergeLabel = (text) => (n) => {
  n.props = { ...(n.props || {}) }
  if (text.trim()) n.props.label = ident(text)
  else delete n.props.label
}

const setEachName = (which, text) => (n) => {
  const name = text.trim() ? ident(text) : null
  n.props[which] = name
  const out = n.outputs.find((o) => o.port === which)
  if (out) out.var = name
}

const setCollectTarget = (text) => (n) => {
  const name = ident(text)
  n.props.target = name
  const out = n.outputs.find((o) => o.port === "results")
  if (out) out.var = name
}

const setErrorName = (text) => (n) => {
  const name = text.trim() ? ident(text) : null
  n.props.error_name = name
  n.outputs = name ? [{ port: "error", var: name }] : []
}

function pairsText(obj) {
  return Object.entries(obj || {})
    .map(([k, v]) => `${k}=${Array.isArray(v) ? `(${v.map(formatLiteral).join(", ")})` : formatLiteral(v)}`)
    .join(" ")
}

function setPairs(n, field, text) {
  const out = {}
  for (const part of text.trim().split(/\s+(?=[A-Za-z_]\w*=)/).filter(Boolean)) {
    const eq = part.indexOf("=")
    if (eq < 1) throw new Error(`expected key=value, got ${part}`)
    out[ident(part.slice(0, eq))] = parseLiteral(part.slice(eq + 1))
  }
  if (Object.keys(out).length) n[field] = out
  else delete n[field]
}
</script>
