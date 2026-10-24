/**
 * The open program. Its text is the source of truth; every view is a
 * projection of it:
 *
 * - the graph document (`doc`, a .kirgraph) for the node and flowchart views,
 *   in the data style they ask for;
 * - the AST (`ast`, see backend core/ast_json.py) for the blocks and sequence
 *   views.
 *
 * An edit in any view rewrites the program: a graph edit goes graph -> text
 * (the graph stays as the user arranged it); a statement edit goes AST ->
 * text -> graph; a text edit goes text -> graph. The actions live in four
 * parts: sync.js (the projections and the backend round trips), history.js
 * (undo and redo of whole snapshots), edits.js (graph edits) and toolchain.js
 * (passes, check, lower, run). Where elements are drawn is not part of the
 * document: the graph views keep it (kir-graph's layout memory).
 */

import { defineStore } from "pinia"

import { editActions } from "./edits"
import { historyActions } from "./history"
import { emptyDoc, syncActions } from "./sync"
import { toolchainActions } from "./toolchain"

export const useDocumentStore = defineStore("document", {
  state: () => ({
    fileName: "untitled.kir",
    text: "",
    doc: emptyDoc(),
    ast: null,
    /** The data style `doc` was drawn in: "variables" or "wires". */
    dataStyle: "variables",
    diagnostics: [],
    graphName: "main",
    /** Bumped on every change of `doc` in place; graph views redraw from it. */
    version: 0,
    /** Bumped when the graph is re-derived from text; graph views lay out afresh. */
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
    ...syncActions,
    ...historyActions,
    ...editActions,
    ...toolchainActions,
  },
})
