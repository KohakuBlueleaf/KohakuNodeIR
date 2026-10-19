<template>
  <footer class="flex items-center gap-3 h-6 px-3 text-[11px] bg-[var(--kt-shell-rail)] dark:bg-warm-950 border-t border-warm-200 dark:border-warm-800 text-warm-600 dark:text-warm-400 shrink-0">
    <span class="font-mono truncate">{{ docStore.fileName }}</span>
    <button class="flex items-center gap-1 hover:text-iolite" @click="ui.showBottom('problems')">
      <span class="i-carbon-error-filled text-coral" />{{ docStore.errorCount }}
      <span class="i-carbon-warning-filled text-amber ml-1" />{{ docStore.warningCount }}
    </button>
    <span>{{ docStore.graph?.nodes.length ?? 0 }} nodes · {{ docStore.graph?.edges.length ?? 0 }} edges</span>
    <span v-if="docStore.doc.uses.length" class="font-mono truncate">@use {{ docStore.doc.uses.map((u) => (u.alias ? `${u.library} as ${u.alias}` : u.library)).join(", ") }}</span>
    <span class="flex-1" />
    <span v-if="docStore.transportError" class="text-coral">backend unreachable</span>
    <button v-if="!ui.bottomOpen" class="flex items-center gap-1 hover:text-iolite" @click="ui.bottomOpen = true"><span class="i-carbon-chevron-up" />panel</button>
  </footer>
</template>

<script setup>
import { useDocumentStore } from "@/stores/document"
import { useUiStore } from "@/stores/ui"

const docStore = useDocumentStore()
const ui = useUiStore()
</script>
