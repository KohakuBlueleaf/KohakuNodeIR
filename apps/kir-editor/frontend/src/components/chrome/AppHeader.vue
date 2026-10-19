<template>
  <header class="flex items-center gap-2 h-11 px-3 bg-[var(--kt-shell-strip)] dark:bg-warm-950 border-b border-warm-200 dark:border-warm-800 shrink-0 min-w-0">
    <div class="flex items-center gap-1.5 pr-2 shrink-0">
      <span class="i-carbon-flow-data text-lg text-iolite dark:text-iolite-light" />
      <span class="font-semibold text-sm text-warm-800 dark:text-warm-100">KIR Editor</span>
      <span class="chip-warm hidden xl:inline-flex">v2 example</span>
    </div>

    <div class="flex items-center gap-0.5">
      <button class="btn-ghost" title="Open .kir, .kirgraph or .kirsig.json" @click="openFile"><span class="i-carbon-folder-open" />Open</button>
      <button class="btn-ghost" title="Save the text" @click="saveKir"><span class="i-carbon-document-download" />.kir</button>
      <button class="btn-ghost" title="Save the graph" @click="saveGraph"><span class="i-carbon-data-structured" />.kirgraph</button>
      <select class="kir-select" title="Load a sample program" :value="''" @change="loadSample($event.target.value)">
        <option value="" disabled>Samples…</option>
        <option v-for="s in SAMPLES" :key="s.id" :value="s.id">{{ s.title }}</option>
      </select>
    </div>

    <div class="w-px h-5 bg-warm-300 dark:bg-warm-700 mx-1" />

    <label class="flex items-center gap-1.5 text-xs text-warm-600 dark:text-warm-300" title="Which graph to show: the top level or a @def">
      <span class="i-carbon-tree-view" />
      <select class="kir-select" :value="docStore.graphName" @change="docStore.selectGraph($event.target.value)">
        <option v-for="g in docStore.graphNames" :key="g" :value="g">{{ g === "main" ? "main" : `@def ${g}` }}</option>
      </select>
    </label>

    <div class="flex items-center rounded-lg bg-warm-200/60 dark:bg-warm-800/60 p-0.5">
      <button v-for="v in VIEWS" :key="v.id" class="kir-seg" :class="{ 'kir-seg--on': ui.view === v.id }" @click="ui.setView(v.id)"><span :class="v.icon" />{{ v.label }}</button>
    </div>

    <span class="flex-1" />

    <span v-if="docStore.syncing" class="text-[11px] text-warm-500 flex items-center gap-1"><span class="i-carbon-circle-dash animate-spin" />sync</span>

    <button class="btn-icon" title="Undo graph edit (Ctrl+Z)" :disabled="!docStore.undoDepth" data-test="undo" @click="docStore.undo()"><span class="i-carbon-undo" /></button>
    <button class="btn-icon" title="Redo (Ctrl+Shift+Z, Ctrl+Y)" :disabled="!docStore.redoDepth" data-test="redo" @click="docStore.redo()"><span class="i-carbon-redo" /></button>
    <label class="flex items-center gap-1 text-[11px] text-warm-600 dark:text-warm-300" title="Write @meta node_id and pos into the text, so ids and positions survive text edits">
      <input type="checkbox" class="accent-iolite" :checked="docStore.withMeta" @change="docStore.setWithMeta($event.target.checked)" />@meta
    </label>
    <button class="btn-ghost" title="Lay the graph out again (ELK)" @click="docStore.relayout()"><span class="i-carbon-chart-network" />Layout</button>
    <button class="btn-ghost" :disabled="!!docStore.busy" @click="run('check')"><span class="i-carbon-task-approved" />Check</button>
    <button class="btn-ghost" :disabled="!!docStore.busy" @click="run('lower')"><span class="i-carbon-flow-stream" />Lower</button>
    <button class="btn-primary" :disabled="!!docStore.busy" @click="run('run')"><span :class="docStore.busy === 'run' ? 'i-carbon-circle-dash animate-spin' : 'i-carbon-play-filled-alt'" />Run</button>
    <button class="btn-icon" :title="ui.dark ? 'Light theme' : 'Dark theme'" @click="ui.toggleTheme()"><span :class="ui.dark ? 'i-carbon-sun' : 'i-carbon-moon'" /></button>
  </header>
</template>

<script setup>
import { SAMPLES } from "@/samples"
import { useDocumentStore } from "@/stores/document"
import { useLibraryStore } from "@/stores/library"
import { VIEWS, useUiStore } from "@/stores/ui"
import { pickFiles, saveFile } from "@/utils/files"

const docStore = useDocumentStore()
const lib = useLibraryStore()
const ui = useUiStore()

const TAB_OF = { check: "problems", lower: "lowered", run: "run" }

async function run(what) {
  await docStore[what]()
  ui.showBottom(TAB_OF[what])
}

function loadSample(id) {
  const s = SAMPLES.find((x) => x.id === id)
  if (s) docStore.loadText(s.text, `${s.id}.kir`)
}

async function openFile() {
  const files = await pickFiles(".kir,.kirgraph,.json", true)
  for (const f of files) {
    try {
      if (f.name.endsWith(".kirsig.json")) {
        lib.addSignatureFile(JSON.parse(f.text))
        await docStore.syncTextToGraph()
      } else if (f.name.endsWith(".kirgraph") || f.name.endsWith(".json")) {
        await docStore.loadGraph(JSON.parse(f.text), f.name)
      } else {
        await docStore.loadText(f.text, f.name)
      }
    } catch (e) {
      docStore.diagnostics = [{ code: "open", severity: "error", message: `${f.name}: ${e.message || e}`, line: null }]
      ui.showBottom("problems")
    }
  }
}

function saveKir() {
  saveFile(docStore.fileName.replace(/\.(kir|kirgraph)$/, "") + ".kir", docStore.text)
}

function saveGraph() {
  const doc = docStore.serializedDoc()
  saveFile(docStore.fileName.replace(/\.kir$/, "") + ".kirgraph", JSON.stringify(doc, null, 2) + "\n", "application/json")
}
</script>

<style>
.kir-select {
  height: 1.75rem;
  padding: 0 0.4rem;
  border-radius: 0.4rem;
  font-size: 11.5px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  max-width: 15rem;
}
.kir-select:focus {
  outline: none;
  border-color: var(--kt-color-iolite);
}
.kir-seg {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  height: 1.5rem;
  padding: 0 0.55rem;
  border-radius: 0.375rem;
  font-size: 11.5px;
  color: var(--color-text-muted);
}
.kir-seg--on {
  background: var(--color-surface);
  color: var(--kt-color-iolite);
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.08);
}
</style>
