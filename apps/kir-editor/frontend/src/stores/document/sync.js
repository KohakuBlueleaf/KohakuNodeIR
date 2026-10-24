/**
 * The projections and the backend round trips: text -> graph and AST
 * (debounced while typing), graph -> text (debounced after graph edits),
 * AST -> text -> graph. A newer sync of the same direction drops the answer
 * of an older one.
 */

import { checkDocument } from "@kohaku/kir-graph"

import { astToText, graphToText, textToGraph } from "@/api/backend"
import { serializeGraph } from "@/graph/edit"
import { useLibraryStore } from "@/stores/library"

const TEXT_DEBOUNCE_MS = 450
const GRAPH_DEBOUNCE_MS = 200

let textTimer = null
let graphTimer = null
let textSeq = 0
let graphSeq = 0

// Where the node view last drew each graph's nodes (graph name -> node id -> {x, y}), for `@meta pos`
const drawn = new Map()

export const emptyDoc = () => ({
  kirgraph: 3,
  uses: [],
  graphs: [{ name: "main", nodes: [], edges: [], regions: [] }],
})

/** Drop the syncs in flight and those waiting on their debounce. */
export function cancelSyncs() {
  clearTimeout(textTimer)
  clearTimeout(graphTimer)
  textSeq++
  graphSeq++
}

export const syncActions = {
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
    if (!this.graphNames.includes(this.graphName)) this.graphName = "main"
    if (this.selectedId && !this.graph.nodes.some((n) => n.id === this.selectedId)) this.selectedId = null
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
    checkDocument(doc)
    this.fileName = (fileName || "untitled.kirgraph").replace(/\.kirgraph$/, ".kir")
    this.doc = doc
    this.graphName = "main"
    this.selectedId = null
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
    const res = await this.call(() => graphToText(this.serializedDoc(), this.scope(), this.withMeta))
    if (seq !== graphSeq) return
    this.syncing = false
    if (!res) return
    this.diagnostics = res.diagnostics
    this.textPending = false
    if (res.text != null) {
      this.text = this.syncedText = res.text
      this.ast = res.ast
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

  // ------------------------------------------------------------ positions in the text
  /** The node view drew graph `name`: `positions` maps node id -> {x, y}. */
  notePositions(name, positions) {
    drawn.set(name, positions)
  },

  setWithMeta(on) {
    this.withMeta = on
    if (on) for (const g of this.doc.graphs) this.stampPositions(g)
    this.syncGraphToText()
  },

  /** Copy where the node view drew a graph's nodes into their `@meta pos`. */
  stampPositions(g) {
    const at = drawn.get(g.name)
    if (!at) return
    for (const n of g.nodes) {
      const p = at.get(n.id)
      if (p) n.meta = { ...(n.meta || {}), pos: [Math.round(p.x), Math.round(p.y)] }
    }
  },

  async selectGraph(name) {
    this.graphName = name
    this.selectedId = null
    this.version++
  },
}
