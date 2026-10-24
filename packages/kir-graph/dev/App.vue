<template>
  <div class="shell" :class="{ dark: theme === 'dark' }">
    <!-- ================================================================ toolbar -->
    <header class="bar">
      <span class="brand"><Icon name="tree-view-alt" /> kir-graph</span>
      <Seg v-model="s.view" :options="VIEW_OPTIONS" label="view" />
      <label v-if="doc" class="field">
        <span class="field__caption">graph</span>
        <select v-model="s.graph">
          <option v-for="g in graphNames" :key="g" :value="g">{{ g }}</option>
        </select>
      </label>
      <Seg v-model="s.regions" :options="[[true, 'boxes'], [false, 'flat']]" label="regions" />
      <Seg v-model="s.fold" :options="FOLD_OPTIONS" label="collapse" />
      <Seg v-model="s.overlay" :options="[['off', 'off'], ['still', 'still'], ['live', 'live']]" label="overlay" />
      <Seg v-model="s.wires" :options="[['rail', 'rail'], ['plain', 'plain']]" label="wires" />
      <Seg v-model="theme" :options="[['light', 'light'], ['dark', 'dark']]" label="theme" />
      <span class="grow" />
      <span v-if="stats" class="stat" :title="`${stats.nodes} nodes, ${stats.regions} regions, ${stats.edges} edges`">
        layout {{ stats.cached ? "cached" : `${stats.ms.toFixed(0)} ms` }} · {{ stats.nodes }}n {{ stats.edges }}e · {{ layouts }} layouts
      </span>
    </header>

    <div class="body">
      <!-- ============================================================ examples -->
      <aside class="side">
        <input v-model="filter" class="search" placeholder="filter examples" />
        <template v-for="group in groups" :key="group.name">
          <div class="side__group">{{ group.name }}</div>
          <button v-for="e in group.items" :key="e.id" class="side__item" :class="{ 'is-on': e.id === s.id, 'is-bad': e.error }" :title="e.error || e.id" :disabled="!!e.error" @click="s.id = e.id">
            <span class="side__title">{{ e.title }}</span>
            <span class="side__count">{{ e.error ? "×" : e.nodes }}</span>
          </button>
        </template>
      </aside>

      <!-- ============================================================ canvas -->
      <main class="main">
        <div v-if="loading" class="hint">loading…</div>
        <template v-else-if="kirgraph">
          <div v-if="s.view === 'all'" class="grid">
            <div v-for="v in SHOWN" :key="v" class="grid__cell">
              <div class="grid__head">{{ v }}</div>
              <KirGraph :doc="kirgraphOf(v)" :graph="s.graph" :view="v" :regions="s.regions" :collapsed="collapsed" :overlay="overlay.nodes" :edge-overlay="overlay.edges" :selected="selectedKey" :theme="theme" :wire-style="s.wires" :minimap="false" @select="onSelect" @update:collapsed="setCollapsed" />
            </div>
          </div>
          <KirGraph v-else ref="graphRef" :doc="kirgraph" :graph="s.graph" :view="s.view" :regions="s.regions" :collapsed="collapsed" :overlay="overlay.nodes" :edge-overlay="overlay.edges" :selected="selectedKey" :theme="theme" :wire-style="s.wires" :layout="layoutOptions" @select="onSelect" @layout="onLayout" @update:collapsed="setCollapsed" />
        </template>
      </main>

      <!-- ============================================================ inspector -->
      <aside class="panel">
        <Seg v-model="tab" :options="[['selection', 'selection'], ['checks', 'checks'], ['source', 'source'], ['json', 'json']]" />
        <div class="panel__body">
          <template v-if="tab === 'selection'">
            <div v-if="!selection" class="hint">Click a node, region or wire.</div>
            <template v-else>
              <div class="kv"><span>type</span><b>{{ selection.type }}</b></div>
              <div class="kv"><span>id</span><code>{{ selection.id }}</code></div>
              <div v-if="selection.node?.path" class="kv"><span>path</span><code>{{ selection.node.path }}</code></div>
              <div v-if="selection.node?.region" class="kv"><span>region</span><code>{{ selection.node.region }}</code></div>
              <div v-if="selection.node?.origin" class="kv"><span>origin</span><code>{{ selection.node.origin.module }}:{{ selection.node.origin.line }}</code></div>
              <div v-if="liveEntry" class="kv"><span>overlay</span><code>{{ JSON.stringify(liveEntry) }}</code></div>
              <pre class="json">{{ JSON.stringify(selectedRaw, null, 1) }}</pre>
            </template>
          </template>
          <template v-else-if="tab === 'checks'">
            <div v-if="!checks" class="hint">Checks run on every layout of a graph view.</div>
            <template v-else>
              <div v-for="(list, name) in checks" :key="name" class="check" :class="list.length ? 'is-bad' : 'is-ok'">
                <Icon :name="list.length ? 'error-filled' : 'checkmark-filled'" />
                <span>{{ name }}</span>
                <b>{{ list.length }}</b>
              </div>
              <pre v-if="failures.length" class="json">{{ JSON.stringify(failures.slice(0, 20), null, 1) }}</pre>
            </template>
          </template>
          <template v-else-if="tab === 'source'">
            <pre class="listing"><span v-for="(line, i) in sourceLines" :key="i" class="listing__line" :class="{ 'is-on': i + 1 === selectedLine }"><i>{{ i + 1 }}</i>{{ line }}
</span></pre>
          </template>
          <pre v-else class="json">{{ jsonText }}</pre>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from "vue"

import { Icon, KirGraph, checkLayout, graphModel, viewData } from "@kohaku/kir-graph"

import { simulate } from "./overlaySim.js"
import Seg from "./Seg.vue"

// The views under review; the library keeps the others (frames, dataflow, sequence)
const SHOWN = ["flowchart", "nodes", "blocks"]
const VIEW_OPTIONS = [...SHOWN.map((v) => [v, v]), ["all", "side by side"]]
const FOLD_OPTIONS = [
  ["none", "none"],
  ["top", "top level"],
  ["d1", "below depth 1"],
]

const s = reactive({ id: "gbc__gbc", view: "flowchart", graph: "main", regions: true, fold: "none", overlay: "live", wires: "rail", layering: "", placement: "" })
// ELK strategies from the URL hash (empty: the library's defaults)
const layoutOptions = computed(() => ({ ...(s.layering ? { layering: s.layering } : {}), ...(s.placement ? { placement: s.placement } : {}) }))
const theme = ref("light")
const tab = ref("selection")
const filter = ref("")
const index = ref([])
const doc = shallowRef(null)
const loading = ref(false)
const stats = ref(null)
const checks = ref(null)
const layouts = ref(0)
const selection = ref(null)
const graphRef = ref(null)

// The URL hash keeps the review state across reloads
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1))
  for (const k of Object.keys(s)) if (p.has(k)) s[k] = k === "regions" ? p.get(k) === "true" : p.get(k)
  if (p.has("theme")) theme.value = p.get("theme")
}
readHash()
watch([s, theme], () => {
  const p = new URLSearchParams({ ...Object.fromEntries(Object.entries(s).map(([k, v]) => [k, String(v)])), theme: theme.value })
  history.replaceState(null, "", `#${p}`)
})

fetch("/index.json")
  .then((r) => r.json())
  .then((list) => (index.value = list))

watch(
  () => s.id,
  async (id) => {
    loading.value = true
    try {
      doc.value = await (await fetch(`/${id}.json`)).json()
      if (!graphNames.value.includes(s.graph)) s.graph = "main"
    } finally {
      loading.value = false
    }
    selection.value = null
  },
  { immediate: true },
)

const groups = computed(() => {
  const f = filter.value.toLowerCase()
  const out = new Map()
  for (const e of index.value) {
    if (f && !`${e.id} ${e.title}`.toLowerCase().includes(f)) continue
    if (!out.has(e.group)) out.set(e.group, [])
    out.get(e.group).push(e)
  }
  return [...out].map(([name, items]) => ({ name, items }))
})

// Each view draws the KIR data style it is made for
const kirgraphOf = (view) => doc.value?.graphs?.[viewData(view)] || null
const kirgraph = computed(() => kirgraphOf(s.view === "all" ? "flowchart" : s.view))
const graphNames = computed(() => (kirgraph.value?.graphs || []).map((g) => g.name))
const model = computed(() => (kirgraph.value && graphNames.value.includes(s.graph) ? graphModel(kirgraph.value, s.graph) : null))

// Collapse: none, every top-level region, or every region below depth 1
const own = ref(null)
watch(() => [s.fold, model.value], () => (own.value = null))
const collapsed = computed(() => {
  if (own.value) return own.value
  if (!model.value || s.fold === "none") return []
  const depth = s.fold === "top" ? 0 : 1
  return [...model.value.regions.values()].filter((r) => r.depth === depth).map((r) => r.id)
})
const setCollapsed = (list) => (own.value = list)

// Overlay: a made-up runtime, still or animated
const t = ref(0)
let timer = null
watch(
  () => s.overlay,
  (mode) => {
    clearInterval(timer)
    if (mode === "live") timer = setInterval(() => (t.value += 0.5), 500)
  },
  { immediate: true },
)
onBeforeUnmount(() => clearInterval(timer))
const overlay = computed(() => (s.overlay === "off" || !model.value ? { nodes: null, edges: null } : simulate(model.value, t.value)))

const selectedKey = computed(() => selection.value?.key ?? null)
const selectedRaw = computed(() => {
  const sel = selection.value
  if (!sel || !model.value) return null
  if (sel.type === "node") return model.value.byId.get(sel.id)
  if (sel.type === "region") return model.value.regions.get(sel.id)
  return sel
})
const liveEntry = computed(() => (selection.value?.key && overlay.value.nodes?.get(selection.value.key)) || null)
const selectedLine = computed(() => selection.value?.node?.origin?.line ?? null)
const sourceLines = computed(() => (doc.value?.source || "").split("\n"))
const jsonText = computed(() => JSON.stringify(kirgraph.value?.graphs?.find((g) => g.name === s.graph) ?? null, null, 1))
const failures = computed(() => Object.entries(checks.value || {}).flatMap(([k, list]) => list.map((x) => [k, x])))

function onSelect(sel) {
  selection.value = sel
}

function onLayout(st) {
  stats.value = st
  layouts.value++
  checks.value = checkLayout(st.layout)
}

watch(
  () => [s.view, s.graph, s.id],
  () => {
    stats.value = null
    checks.value = null
  },
)
</script>
