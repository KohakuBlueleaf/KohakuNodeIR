/**
 * The open program, held twice: as KIR text and as its graph document (.kirgraph).
 *
 * Editing the text re-derives the graph through the backend (text -> graph)
 * and lays it out again. Editing the graph re-derives the text (graph ->
 * text) and leaves the graph and its layout as the user arranged them.
 *
 * Every graph edit and every text change applied to the graph first records
 * a snapshot (graph document, positions, matching text); undo and redo swap
 * whole snapshots. Opening a file or sample starts a new history.
 */

import { defineStore } from "pinia"

import {
  checkText,
  graphToText,
  listPasses,
  lowerText,
  runText,
  textToGraph,
} from "@/api/backend"
import {
  addArm,
  connect,
  isValidConnection,
  makeNode,
  removeArm,
  removeEdges,
  removeNodes,
  serializeGraph,
  toggleDefault,
} from "@/graph/edit"
import { layoutGraph, membership } from "@/graph/layout"
import { useLibraryStore } from "@/stores/library"

const TEXT_DEBOUNCE_MS = 450
const GRAPH_DEBOUNCE_MS = 200

const HISTORY_LIMIT = 100

let textTimer = null
let graphTimer = null
let textSeq = 0
let graphSeq = 0

// Undo / redo: bounded stacks of whole-document snapshots, kept outside the
// reactive state so they are never proxied.
const undoStack = []
const redoStack = []

const EMPTY_DOC = () => ({
  kirgraph: 2,
  uses: [],
  graphs: [{ name: "main", nodes: [], edges: [] }],
})

export const useDocumentStore = defineStore("document", {
  state: () => ({
    fileName: "untitled.kir",
    text: "",
    doc: EMPTY_DOC(),
    outline: null,
    diagnostics: [],
    graphName: "main",
    /** Per graph name: `{positions, absolute, frames, routes}` from ELK plus user moves. */
    layouts: {},
    /** Bumped on every graph change; the canvas rebuilds its nodes from it. */
    version: 0,
    selectedId: null,
    /** Write `@meta node_id=… pos=(…)` into the text, so ids and positions survive it. */
    withMeta: false,
    /** Place nodes at their `@meta pos` when the text has one. */
    useSavedPositions: true,
    syncing: false,
    layingOut: false,
    layoutError: null,
    runResult: null,
    lowerResult: null,
    /** The backend's optimization passes `[{name, doc, needs}]`, and the names switched on. */
    passCatalog: [],
    passesOn: [],
    busy: null,
    transportError: null,
    /** A graph edit whose text has not come back from the backend yet. */
    textPending: false,
    /** The text the current graph was derived from or turned into. */
    syncedText: null,
    undoDepth: 0,
    redoDepth: 0,
  }),

  getters: {
    graph: (s) => s.doc.graphs.find((g) => g.name === s.graphName) || s.doc.graphs[0],
    graphNames: (s) => s.doc.graphs.map((g) => g.name),
    defNames: (s) => new Set(s.doc.graphs.map((g) => g.name).filter((n) => n !== "main")),
    layout: (s) => s.layouts[s.graphName] || null,
    selected() {
      return this.graph?.nodes.find((n) => n.id === this.selectedId) || null
    },
    errorCount: (s) => s.diagnostics.filter((d) => d.severity === "error").length,
    warningCount: (s) => s.diagnostics.filter((d) => d.severity === "warning").length,
  },

  actions: {
    scope() {
      return useLibraryStore().scope
    },

    async call(fn) {
      try {
        const out = await fn()
        this.transportError = null
        return out
      } catch (e) {
        this.transportError = String(e.message || e)
        return null
      }
    },

    // ------------------------------------------------------------ history
    snapshot() {
      const layouts = {}
      for (const [name, l] of Object.entries(this.layouts))
        layouts[name] = { ...l, positions: { ...l.positions } }
      return {
        doc: JSON.parse(JSON.stringify(this.doc)),
        layouts,
        // The text that matches this graph (the editor may hold newer, unsynced text).
        text: this.syncedText ?? this.text,
        outline: this.outline,
        graphName: this.graphName,
        textPending: this.textPending,
      }
    },

    /** Remember the state before an edit; a new edit drops what could be redone. */
    record() {
      undoStack.push(this.snapshot())
      if (undoStack.length > HISTORY_LIMIT) undoStack.shift()
      redoStack.length = 0
      this.undoDepth = undoStack.length
      this.redoDepth = 0
    },

    clearHistory() {
      undoStack.length = 0
      redoStack.length = 0
      this.undoDepth = 0
      this.redoDepth = 0
    },

    restore(s) {
      // Drop syncs in flight: they belong to the state being left.
      clearTimeout(textTimer)
      clearTimeout(graphTimer)
      textSeq++
      graphSeq++
      this.syncing = false
      this.doc = s.doc
      this.layouts = s.layouts
      this.outline = s.outline
      this.graphName = this.doc.graphs.some((g) => g.name === s.graphName) ? s.graphName : "main"
      if (this.selectedId && !this.graph.nodes.some((n) => n.id === this.selectedId))
        this.selectedId = null
      this.version++
      // The text kept in the snapshot is exact (comments included) unless the
      // graph edit before it had not come back as text yet.
      if (s.textPending) {
        this.textPending = true
        this.syncGraphToText()
      } else {
        this.text = this.syncedText = s.text
        this.textPending = false
        this.check()
      }
    },

    undo() {
      if (!undoStack.length) return
      redoStack.push(this.snapshot())
      this.restore(undoStack.pop())
      this.undoDepth = undoStack.length
      this.redoDepth = redoStack.length
    },

    redo() {
      if (!redoStack.length) return
      undoStack.push(this.snapshot())
      this.restore(redoStack.pop())
      this.undoDepth = undoStack.length
      this.redoDepth = redoStack.length
    },

    // ------------------------------------------------------------ text -> graph
    async loadText(text, fileName) {
      this.fileName = fileName || this.fileName
      this.text = text
      this.selectedId = null
      this.runResult = null
      this.lowerResult = null
      await this.syncTextToGraph()
      this.clearHistory()
    },

    /** The text editor changed the text. */
    editText(text) {
      if (text === this.text) return
      this.text = text
      clearTimeout(textTimer)
      textTimer = setTimeout(() => this.syncTextToGraph(), TEXT_DEBOUNCE_MS)
    },

    async syncTextToGraph() {
      clearTimeout(textTimer)
      const seq = ++textSeq
      this.syncing = true
      const res = await this.call(() => textToGraph(this.text, this.scope()))
      if (seq !== textSeq) return
      this.syncing = false
      if (!res) return
      this.diagnostics = res.diagnostics
      if (!res.graph) return
      this.record()
      this.syncedText = this.text
      this.doc = res.graph
      this.outline = res.outline
      if (!this.graphNames.includes(this.graphName)) this.graphName = "main"
      if (this.selectedId && !this.graph.nodes.some((n) => n.id === this.selectedId))
        this.selectedId = null
      this.layouts = {}
      this.version++
      await this.relayout()
    },

    // ------------------------------------------------------------ graph -> text
    async loadGraph(doc, fileName) {
      if (doc?.kirgraph !== 2 || !Array.isArray(doc.graphs))
        throw new Error("not a .kirgraph file (kirgraph 2)")
      this.fileName = (fileName || "untitled.kirgraph").replace(/\.kirgraph$/, ".kir")
      this.doc = doc
      this.graphName = "main"
      this.selectedId = null
      this.layouts = {}
      this.version++
      await Promise.all([this.syncGraphToText(), this.relayout()])
      this.clearHistory()
    },

    /** The graph changed: redraw now, rewrite the text shortly. */
    commitGraph() {
      this.version++
      this.textPending = true
      clearTimeout(graphTimer)
      graphTimer = setTimeout(() => this.syncGraphToText(), GRAPH_DEBOUNCE_MS)
    },

    serializedDoc() {
      return { ...this.doc, graphs: this.doc.graphs.map(serializeGraph) }
    },

    async syncGraphToText() {
      clearTimeout(graphTimer)
      const seq = ++graphSeq
      this.syncing = true
      const res = await this.call(() =>
        graphToText(this.serializedDoc(), this.scope(), this.withMeta),
      )
      if (seq !== graphSeq) return
      this.syncing = false
      if (!res) return
      this.diagnostics = res.diagnostics
      this.textPending = false
      if (res.text != null) {
        this.text = this.syncedText = res.text
        this.outline = res.outline
      }
    },

    setWithMeta(on) {
      this.withMeta = on
      if (on) for (const g of this.doc.graphs) this.stampPositions(g.name)
      this.syncGraphToText()
    },

    /** Copy the canvas positions of a graph's nodes into their `@meta pos`. */
    stampPositions(name) {
      const layout = this.layouts[name]
      const g = this.doc.graphs.find((x) => x.name === name)
      if (!layout || !g) return
      for (const n of g.nodes) {
        const p = layout.positions[n.id]
        if (p) n.meta = { ...(n.meta || {}), pos: [Math.round(p.x), Math.round(p.y)] }
      }
    },

    // ------------------------------------------------------------ layout
    async relayout(name = this.graphName) {
      const g = this.doc.graphs.find((x) => x.name === name)
      if (!g) return
      this.layingOut = true
      try {
        const layout = await layoutGraph(g, { defNames: this.defNames })
        if (this.useSavedPositions) {
          const memberOf = membership(g)
          for (const n of g.nodes) {
            const pos = n.meta?.pos
            if (Array.isArray(pos) && pos.length === 2 && !memberOf.has(n.id))
              layout.positions[n.id] = { x: pos[0], y: pos[1] }
          }
        }
        this.layouts = { ...this.layouts, [name]: layout }
        this.layoutError = null
        this.version++
      } catch (e) {
        this.layoutError = String(e?.message || e)
      } finally {
        this.layingOut = false
      }
    },

    async selectGraph(name) {
      this.graphName = name
      this.selectedId = null
      this.version++
      if (!this.layouts[name]) await this.relayout(name)
    },

    // ------------------------------------------------------------ edits
    addNode(spec, position) {
      this.record()
      const g = this.graph
      if (spec.use && !this.doc.uses.some((u) => u.library === spec.use.library))
        this.doc.uses.push(spec.use)
      const node = makeNode(g, spec)
      g.nodes.push(node)
      if (this.layout) this.layout.positions[node.id] = position
      this.selectedId = node.id
      this.commitGraph()
      return node
    },

    connect(connection) {
      if (!isValidConnection(connection)) return
      this.record()
      if (connect(this.graph, connection)) this.commitGraph()
      else this.dropRecord()
    },

    /** Forget the last `record()`: the edit it was made for did not happen. */
    dropRecord() {
      undoStack.pop()
      this.undoDepth = undoStack.length
    },

    removeNodes(ids) {
      if (!ids.length) return
      this.record()
      const g = this.graph
      const layout = this.layout
      const memberOf = membership(g)
      const orphans = removeNodes(g, ids)
      if (layout) {
        // A removed frame's members keep their place on the page.
        for (const m of orphans) {
          const frame = layout.positions[memberOf.get(m)]
          const rel = layout.positions[m]
          if (frame && rel) layout.positions[m] = { x: frame.x + rel.x, y: frame.y + rel.y }
        }
      }
      if (ids.includes(this.selectedId)) this.selectedId = null
      this.commitGraph()
    },

    removeEdges(keys) {
      if (!keys.length) return
      this.record()
      removeEdges(this.graph, keys)
      this.commitGraph()
    },

    moveNode(id, position) {
      if (!this.layout) return
      this.layout.positions[id] = { x: position.x, y: position.y }
      if (this.withMeta) {
        const n = this.graph.nodes.find((x) => x.id === id)
        if (n) {
          n.meta = { ...(n.meta || {}), pos: [Math.round(position.x), Math.round(position.y)] }
          this.commitGraph()
        }
      }
    },

    /** Change the selected node through `fn(node, graph)`. */
    updateSelected(fn) {
      const n = this.selected
      if (!n) return
      this.record()
      try {
        fn(n, this.graph)
      } catch (e) {
        // A rejected value (fn validates before it writes) leaves the node as it was.
        this.dropRecord()
        throw e
      }
      this.commitGraph()
    },

    addArm() {
      this.updateSelected((n, g) => addArm(g, n))
    },
    removeArm() {
      this.updateSelected((n, g) => removeArm(g, n))
    },
    toggleDefault() {
      this.updateSelected((n, g) => toggleDefault(g, n))
    },

    // ------------------------------------------------------------ toolchain
    async loadPasses() {
      const passes = await this.call(listPasses)
      if (!passes) return
      this.passCatalog = passes
      this.passesOn = passes.map((p) => p.name)
    },

    /** Switch a pass; switching one on also switches on what it needs, off also what needs it. */
    togglePass(name) {
      const on = new Set(this.passesOn)
      const needs = (n) => this.passCatalog.find((p) => p.name === n)?.needs || []
      if (on.has(name)) {
        const drop = (n) => {
          on.delete(n)
          for (const p of this.passCatalog) if (on.has(p.name) && needs(p.name).includes(n)) drop(p.name)
        }
        drop(name)
      } else {
        const add = (n) => {
          on.add(n)
          for (const r of needs(n)) if (!on.has(r)) add(r)
        }
        add(name)
      }
      this.passesOn = this.passCatalog.map((p) => p.name).filter((n) => on.has(n))
    },

    /** The passes to send: null when all are on (the backend default). */
    selectedPasses() {
      return this.passesOn.length === this.passCatalog.length ? null : [...this.passesOn]
    },

    async check() {
      this.busy = "check"
      const res = await this.call(() => checkText(this.text, this.scope()))
      this.busy = null
      if (res) this.diagnostics = res.diagnostics
    },

    async lower() {
      this.busy = "lower"
      const res = await this.call(() => lowerText(this.text, this.scope(), this.selectedPasses()))
      this.busy = null
      if (res) {
        this.lowerResult = res
        this.diagnostics = res.diagnostics
      }
    },

    async run() {
      this.busy = "run"
      const res = await this.call(() => runText(this.text, this.scope(), this.selectedPasses()))
      this.busy = null
      if (res) {
        this.runResult = res
        this.diagnostics = res.diagnostics
      }
    },
  },
})
