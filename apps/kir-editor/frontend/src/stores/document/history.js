/**
 * Undo and redo: every edit first records a snapshot (graph, AST, the text
 * that matches them); undo and redo swap whole snapshots. Opening a file or
 * sample starts a new history. The stacks live outside the reactive state,
 * so snapshots are never proxied.
 */

import { cancelSyncs } from "./sync"

const HISTORY_LIMIT = 100
const undoStack = []
const redoStack = []

const clone = (x) => (x == null ? x : JSON.parse(JSON.stringify(x)))

export const historyActions = {
  snapshot() {
    return {
      doc: clone(this.doc),
      ast: this.ast,
      // The text that matches this graph (the editor may hold newer, unsynced text)
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
    // Syncs in flight belong to the state being left
    cancelSyncs()
    this.syncing = false
    this.doc = s.doc
    this.ast = s.ast
    this.graphName = this.doc.graphs.some((g) => g.name === s.graphName) ? s.graphName : "main"
    if (this.selectedId && !this.graph.nodes.some((n) => n.id === this.selectedId)) this.selectedId = null
    this.version++
    // The snapshot's text is exact (comments included) unless the graph edit before it had not come back as text yet
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
}
