/**
 * The open program. Its text is the source of truth; every view is a
 * projection of it:
 *
 * - the graph document (`doc`, a .kirgraph) for the node and flowchart views,
 *   in the data style they ask for, with `structure` (each graph's statements
 *   tagged with their node ids, for drawing control as frames);
 * - the AST (`ast`, see backend core/ast_json.py) for the blocks and sequence
 *   views.
 *
 * An edit in any view rewrites the program: a graph edit goes graph -> text
 * (the graph and its layout stay as the user arranged them); a statement edit
 * goes AST -> text -> graph; a text edit goes text -> graph. Every edit first
 * records a snapshot (graph, AST, layouts, matching text); undo and redo swap
 * whole snapshots. Opening a file or sample starts a new history.
 */

import { defineStore } from "pinia"

import {
  astToText,
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
  insertAfter,
  isValidConnection,
  makeNode,
  removeArm,
  removeEdges,
  removeNodes,
  serializeGraph,
  toggleDefault,
} from "@/graph/edit"
import { membership } from "@/graph/layout"
import { useLibraryStore } from "@/stores/library"

const TEXT_DEBOUNCE_MS = 450
const GRAPH_DEBOUNCE_MS = 200
const HISTORY_LIMIT = 100

let textTimer = null
let graphTimer = null
let textSeq = 0
let graphSeq = 0

// Undo / redo stacks, outside the reactive state so snapshots are never proxied.
const undoStack = []
const redoStack = []

const EMPTY_DOC = () => ({
  kirgraph: 2,
  uses: [],
  graphs: [{ name: "main", nodes: [], edges: [] }],
})

const clone = (x) => (x == null ? x : JSON.parse(JSON.stringify(x)))

export const useDocumentStore = defineStore("document", {
  state: () => ({
    fileName: "untitled.kir",
    text: "",
    doc: EMPTY_DOC(),
    ast: null,
    structure: null,
    /** The data style `doc` was drawn in: "variables" or "wires". */
    dataStyle: "variables",
    diagnostics: [],
    graphName: "main",
    /** Per `<style>:<graph>`: `{positions, ...}` from that view's layout plus user moves. */
    layouts: {},
    /** Bumped on every graph change; canvases rebuild their nodes from it. */
    version: 0,
    /** Bumped when the graph is re-derived from text; canvases lay out again. */
    epoch: 0,
    selectedId: null,
    /** Write `@meta node_id=… pos=(…)` into the text, so ids and positions survive it. */
    withMeta: false,
    syncing: false,
    runResult: null,
    lowerResult: null,
    passCatalog: [],
    passesOn: [],
    busy: null,
    transportError: null,
    /** A graph edit whose text has not come back from the backend yet. */
    textPending: false,
    /** The text the current graph and AST were derived from or turned into. */
    syncedText: null,
    undoDepth: 0,
    redoDepth: 0,
  }),

  getters: {
    graph: (s) => s.doc.graphs.find((g) => g.name === s.graphName) || s.doc.graphs[0],
    graphNames: (s) => s.doc.graphs.map((g) => g.name),
    defNames: (s) => new Set(s.doc.graphs.map((g) => g.name).filter((n) => n !== "main")),
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

    layoutKey(style, graph = this.graphName) {
      return `${style}:${graph}`
    },

    setLayout(key, layout) {
      this.layouts = { ...this.layouts, [key]: layout }
      this.version++
    },

    // ------------------------------------------------------------ history
    snapshot() {
      const layouts = {}
      for (const [key, l] of Object.entries(this.layouts))
        layouts[key] = { ...l, positions: { ...l.positions } }
      return {
        doc: clone(this.doc),
        ast: this.ast,
        structure: this.structure,
        layouts,
        // The text that matches this graph (the editor may hold newer, unsynced text).
        text: this.syncedText ?? this.text,
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

    /** Forget the last `record()`: the edit it was made for did not happen. */
    dropRecord() {
      undoStack.pop()
      this.undoDepth = undoStack.length
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
      this.ast = s.ast
      this.structure = s.structure
      this.layouts = s.layouts
      this.graphName = this.doc.graphs.some((g) => g.name === s.graphName) ? s.graphName : "main"
      if (this.selectedId && !this.graph.nodes.some((n) => n.id === this.selectedId))
        this.selectedId = null
      this.version++
      // The snapshot's text is exact (comments included) unless the graph
      // edit before it had not come back as text yet.
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

    // ------------------------------------------------------------ text -> projections
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

    /** Re-derive the graph (in the wanted data style) and the AST from the text. */
    async syncTextToGraph({ record = true } = {}) {
      clearTimeout(textTimer)
      const seq = ++textSeq
      this.syncing = true
      const style = this.dataStyle
      const res = await this.call(() => textToGraph(this.text, this.scope(), style))
      if (seq !== textSeq) return
      this.syncing = false
      if (!res) return
      this.diagnostics = res.diagnostics
      if (!res.graph) return
      if (record) this.record()
      this.syncedText = this.text
      this.doc = res.graph
      this.ast = res.ast
      this.structure = res.structure
      if (!this.graphNames.includes(this.graphName)) this.graphName = "main"
      if (this.selectedId && !this.graph.nodes.some((n) => n.id === this.selectedId))
        this.selectedId = null
      this.layouts = {}
      this.epoch++
      this.version++
    },

    /** Draw the graph in another data style ("variables" or "wires"); the text is unchanged. */
    async setDataStyle(style) {
      if (style === this.dataStyle) return
      this.dataStyle = style
      if (this.textPending) await this.syncGraphToText()
      await this.syncTextToGraph({ record: false })
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
      this.epoch++
      this.version++
      await this.syncGraphToText()
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
        this.ast = res.ast
        this.structure = res.structure
        this.version++
      }
    },

    // ------------------------------------------------------------ AST -> text
    /** A statement view edited the program: write it, then re-derive every projection. */
    async applyAst(ast) {
      this.syncing = true
      const res = await this.call(() => astToText(ast, this.scope()))
      this.syncing = false
      if (!res) return false
      if (res.text == null) {
        this.diagnostics = res.diagnostics
        return false
      }
      this.text = res.text
      await this.syncTextToGraph()
      return true
    },

    setWithMeta(on) {
      this.withMeta = on
      if (on) for (const g of this.doc.graphs) this.stampPositions(this.layoutKey("nodes", g.name), g)
      this.syncGraphToText()
    },

    /** Copy a layout's positions of a graph's nodes into their `@meta pos`. */
    stampPositions(key, g) {
      const layout = this.layouts[key]
      if (!layout) return
      for (const n of g.nodes) {
        const p = layout.positions[n.id]
        if (p) n.meta = { ...(n.meta || {}), pos: [Math.round(p.x), Math.round(p.y)] }
      }
    },

    async selectGraph(name) {
      this.graphName = name
      this.selectedId = null
      this.version++
    },

    // ------------------------------------------------------------ graph edits
    /**
     * Add a node. `position` is in the coordinates of layout `key`;
     * `after`: a node on the control chain to insert the new one behind.
     */
    addNode(spec, position, key, after = null) {
      this.record()
      const g = this.graph
      if (spec.use && !this.doc.uses.some((u) => u.library === spec.use.library))
        this.doc.uses.push(spec.use)
      const node = makeNode(g, spec)
      g.nodes.push(node)
      if (after) insertAfter(g, after, node)
      if (key && this.layouts[key]) this.layouts[key].positions[node.id] = position
      this.selectedId = node.id
      this.commitGraph()
      return node
    },

    connect(connection) {
      if (!isValidConnection(connection, this.graph)) return
      this.record()
      if (connect(this.graph, connection)) this.commitGraph()
      else this.dropRecord()
    },

    removeNodes(ids, key = null) {
      if (!ids.length) return
      this.record()
      const g = this.graph
      const layout = key ? this.layouts[key] : null
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

    moveNode(key, id, position) {
      const layout = this.layouts[key]
      if (!layout) return
      layout.positions[id] = { x: position.x, y: position.y }
      if (this.withMeta) {
        const n = this.graph.nodes.find((x) => x.id === id)
        if (n) {
          n.meta = { ...(n.meta || {}), pos: [Math.round(position.x), Math.round(position.y)] }
          this.commitGraph()
        }
      }
    },

    /** Change a node through `fn(node, graph)`; `fn` validates before it writes. */
    updateNode(id, fn) {
      const n = this.graph.nodes.find((x) => x.id === id)
      if (!n) return
      this.record()
      try {
        fn(n, this.graph)
      } catch (e) {
        this.dropRecord()
        throw e
      }
      this.commitGraph()
    },

    updateSelected(fn) {
      if (this.selectedId) this.updateNode(this.selectedId, fn)
    },

    /** Set (or with `undefined`, clear) the literal in an input box. */
    setInputValue(id, port, value) {
      this.updateNode(id, (n) => {
        if (n.kind === "value") {
          n.props.value = value === undefined ? null : value
          return
        }
        let p = (n.inputs || []).find((x) => x.port === port)
        if (!p) {
          p = { port, keyword: true }
          n.inputs.push(p)
        }
        if (value === undefined) delete p.value
        else p.value = value
      })
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
