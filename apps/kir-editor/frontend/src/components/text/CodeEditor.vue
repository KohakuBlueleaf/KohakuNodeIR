<template>
  <div ref="host" class="kir-code h-full w-full overflow-hidden" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import { basicSetup } from "codemirror"
import { Annotation, EditorSelection, EditorState } from "@codemirror/state"
import { EditorView, keymap } from "@codemirror/view"
import { indentWithTab } from "@codemirror/commands"
import { indentUnit } from "@codemirror/language"
import { lintGutter, setDiagnostics } from "@codemirror/lint"

import { kir } from "@/components/text/kirLanguage"
import { useDocumentStore } from "@/stores/document"
import { useUiStore } from "@/stores/ui"

const docStore = useDocumentStore()
const ui = useUiStore()
const host = ref(null)
let view = null

// Changes the store pushes into the editor; only other changes are user edits.
const External = Annotation.define()

function toCm(diagnostics, doc) {
  const out = []
  for (const d of diagnostics) {
    const n = d.line && d.line <= doc.lines ? d.line : 1
    const line = doc.line(n)
    out.push({
      from: line.from,
      to: Math.max(line.from, line.to),
      severity: d.severity === "warning" ? "warning" : "error",
      message: `${d.code}: ${d.message}`,
    })
  }
  return out
}

function pushDiagnostics() {
  if (!view) return
  view.dispatch(setDiagnostics(view.state, toCm(docStore.diagnostics, view.state.doc)))
}

onMounted(() => {
  view = new EditorView({
    parent: host.value,
    state: EditorState.create({
      doc: docStore.text,
      extensions: [
        basicSetup,
        keymap.of([indentWithTab]),
        indentUnit.of("    "),
        EditorState.tabSize.of(4),
        kir(),
        lintGutter(),
        EditorView.updateListener.of((u) => {
          if (!u.docChanged || u.transactions.some((tr) => tr.annotation(External))) return
          docStore.editText(u.state.doc.toString())
        }),
      ],
    }),
  })
  pushDiagnostics()
})

onBeforeUnmount(() => view?.destroy())

watch(
  () => docStore.text,
  (text) => {
    if (!view || view.state.doc.toString() === text) return
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: text },
      annotations: External.of(true),
    })
    pushDiagnostics()
  },
)

watch(() => docStore.diagnostics, pushDiagnostics)

watch(
  () => ui.reveal,
  (r) => {
    if (!view || !r || r.line > view.state.doc.lines) return
    const line = view.state.doc.line(r.line)
    view.dispatch({
      selection: EditorSelection.range(line.from, line.to),
      effects: EditorView.scrollIntoView(line.from, { y: "center" }),
    })
    view.focus()
  },
)
</script>
