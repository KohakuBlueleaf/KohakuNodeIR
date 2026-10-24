/**
 * Graph edits. Each records a snapshot first (history.js), changes the
 * current graph in place through graph/edit.js, and commits it: the views
 * redraw at once and the text follows (sync.js).
 */

import { addArm, connect, insertAfter, isValidConnection, makeNode, removeArm, removeEdges, removeNodes, toggleDefault } from "@/graph/edit"

export const editActions = {
  /**
   * Add a node; returns it. `after`: a node on the control chain to insert it
   * behind; `region`: the region it is drawn in until the text is read back.
   */
  addNode(spec, { after = null, region = null } = {}) {
    this.record()
    const g = this.graph
    if (spec.use && !this.doc.uses.some((u) => u.library === spec.use.library)) this.doc.uses.push(spec.use)
    const node = makeNode(g, spec)
    if (region) node.region = region
    g.nodes.push(node)
    if (after) insertAfter(g, after, node)
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

  removeNodes(ids) {
    if (!ids.length) return
    this.record()
    removeNodes(this.graph, ids)
    if (ids.includes(this.selectedId)) this.selectedId = null
    this.commitGraph()
  },

  removeEdges(keys) {
    if (!keys.length) return
    this.record()
    removeEdges(this.graph, keys)
    this.commitGraph()
  },

  /** A node was dragged to `position`; with `withMeta` on, its `@meta pos` follows. */
  moveNode(id, position) {
    if (!this.withMeta) return
    const n = this.graph.nodes.find((x) => x.id === id)
    if (!n) return
    n.meta = { ...(n.meta || {}), pos: [Math.round(position.x), Math.round(position.y)] }
    this.commitGraph()
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
}
