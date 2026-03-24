import { ref, onMounted, onUnmounted } from 'vue'
import { useGraphStore } from '../stores/graph.js'
import { useEditorStore } from '../stores/editor.js'
import { useHistoryStore } from '../stores/history.js'
import { detectAndParseAsync } from '../parser/index.js'

/**
 * useKeyboard
 *
 * Global keyboard shortcut handling for the node editor.
 *
 * Optional callbacks:
 *   onCancelOperation()   — called on Escape; should cancel draft wires,
 *                           box selection, etc.  Typically wired to
 *                           useWireDraw.cancelDraw and
 *                           useSelection.cancelSelection.
 */
export function useKeyboard({ onCancelOperation } = {}) {
  const graphStore = useGraphStore()
  const editorStore = useEditorStore()
  const historyStore = useHistoryStore()

  // Exposed so the template / usePanZoom can check pan-mode state
  const spaceHeld = ref(false)

  // ---------------------------------------------------------------------------
  // Guards
  // ---------------------------------------------------------------------------

  function isEditingText() {
    const tag = document.activeElement?.tagName
    return tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable
  }

  // ---------------------------------------------------------------------------
  // Key down
  // ---------------------------------------------------------------------------

  function onKeyDown(e) {
    // Space — enable pan mode
    if (e.code === 'Space' && !e.repeat) {
      if (!isEditingText()) {
        spaceHeld.value = true
        editorStore.setSpacePanActive(true)
        e.preventDefault()
      }
      return
    }

    // Don't fire shortcuts when the user is typing
    if (isEditingText()) return

    const ctrl = e.ctrlKey || e.metaKey

    // Escape — cancel current operation
    if (e.key === 'Escape') {
      if (typeof onCancelOperation === 'function') onCancelOperation()
      return
    }

    // Delete / Backspace — delete selected nodes
    if (e.key === 'Delete' || e.key === 'Backspace') {
      deleteSelected()
      return
    }

    // Ctrl+A — select all nodes
    if (ctrl && e.key === 'a') {
      e.preventDefault()
      editorStore.setSelection(graphStore.nodeList.map((n) => n.id))
      return
    }

    // Ctrl+V — paste KIR text or graph JSON from clipboard
    if (ctrl && e.key === 'v') {
      e.preventDefault()
      handlePaste()
      return
    }

    // Ctrl+Z — undo
    if (ctrl && !e.shiftKey && e.key === 'z') {
      e.preventDefault()
      historyStore.undo()
      return
    }

    // Ctrl+Shift+Z — redo
    if (ctrl && e.shiftKey && e.key === 'z') {
      e.preventDefault()
      historyStore.redo()
      return
    }

    // Ctrl+Y — redo (Windows convention)
    if (ctrl && e.key === 'y') {
      e.preventDefault()
      historyStore.redo()
      return
    }
  }

  // ---------------------------------------------------------------------------
  // Key up
  // ---------------------------------------------------------------------------

  function onKeyUp(e) {
    if (e.code === 'Space') {
      spaceHeld.value = false
      editorStore.setSpacePanActive(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function deleteSelected() {
    // Use the store's deleteSelected which handles both nodes and connections
    editorStore.deleteSelected()
  }

  // ---------------------------------------------------------------------------
  // Paste (Ctrl+V) — import KIR text or graph JSON from clipboard
  // ---------------------------------------------------------------------------

  /**
   * Convert parser intermediate format into graph store nodes + connections.
   * Mirrors the parserResultToGraph helper in Toolbar.vue.
   */
  function parserResultToGraph(parserNodes, parserEdges) {
    function makePortId(nodeId, portName, suffix) {
      const safe = portName.replace(/[^a-zA-Z0-9_]/g, '_')
      return `${nodeId}__${safe}__${suffix}`
    }

    const NO_CTRL_TYPES = new Set(['value', 'load'])

    const nodes = parserNodes.map((pn) => {
      const dataInputs = (pn.dataInputs ?? []).map((p) => {
        const port = { id: makePortId(pn.id, p.name, 'di'), name: p.name, dataType: p.type ?? 'any' }
        if (p.default !== undefined) port.defaultValue = p.default
        return port
      })
      const dataOutputs = (pn.dataOutputs ?? []).map((p) => ({
        id: makePortId(pn.id, p.name, 'do'),
        name: p.name,
        dataType: p.type ?? 'any',
      }))
      let rawCtrlIn = pn.ctrlInputs ?? []
      let rawCtrlOut = pn.ctrlOutputs ?? []
      if (!NO_CTRL_TYPES.has(pn.type) && rawCtrlIn.length === 0 && rawCtrlOut.length === 0) {
        rawCtrlIn = ['in']
        rawCtrlOut = ['out']
      }
      const ctrlInputs = rawCtrlIn.map((name) => ({ id: makePortId(pn.id, name, 'ci'), name }))
      const ctrlOutputs = rawCtrlOut.map((name) => ({ id: makePortId(pn.id, name, 'co'), name }))
      return {
        id: pn.id,
        type: pn.type ?? 'function',
        name: pn.name ?? pn.type ?? 'Node',
        x: pn.x ?? 0,
        y: pn.y ?? 0,
        width: pn.width ?? 160,
        height: pn.height ?? 120,
        dataPorts: { inputs: dataInputs, outputs: dataOutputs },
        controlPorts: { inputs: ctrlInputs, outputs: ctrlOutputs },
        properties: {},
      }
    })

    const portIdLookup = new Map()
    for (const node of nodes) {
      for (const p of node.dataPorts.inputs) portIdLookup.set(`${node.id}|${p.name}|di`, p.id)
      for (const p of node.dataPorts.outputs) portIdLookup.set(`${node.id}|${p.name}|do`, p.id)
      for (const p of node.controlPorts.inputs) portIdLookup.set(`${node.id}|${p.name}|ci`, p.id)
      for (const p of node.controlPorts.outputs) portIdLookup.set(`${node.id}|${p.name}|co`, p.id)
    }

    const connections = (parserEdges ?? []).map((edge) => {
      const isCtrl = edge.type === 'control'
      const fromSuffix = isCtrl ? 'co' : 'do'
      const toSuffix = isCtrl ? 'ci' : 'di'
      const fromPortId =
        portIdLookup.get(`${edge.fromNode}|${edge.fromPort}|${fromSuffix}`) ??
        makePortId(edge.fromNode, edge.fromPort, fromSuffix)
      const toPortId =
        portIdLookup.get(`${edge.toNode}|${edge.toPort}|${toSuffix}`) ??
        makePortId(edge.toNode, edge.toPort, toSuffix)
      return {
        fromNodeId: edge.fromNode,
        fromPortId,
        toNodeId: edge.toNode,
        toPortId,
        portType: isCtrl ? 'control' : 'data',
      }
    })

    return { nodes, connections }
  }

  async function handlePaste() {
    let text
    try {
      text = await navigator.clipboard.readText()
    } catch {
      // Clipboard access denied or unavailable — silently ignore
      return
    }

    if (!text || !text.trim()) return

    try {
      const result = await detectAndParseAsync(text)
      if (!result || !result.nodes || result.nodes.length === 0) return

      const { nodes, connections } = parserResultToGraph(result.nodes, result.edges)
      graphStore.clear()
      for (const node of nodes) graphStore.addNode(node)
      for (const conn of connections) {
        graphStore.addConnection(conn.fromNodeId, conn.fromPortId, conn.toNodeId, conn.toPortId, conn.portType)
      }
    } catch {
      // Parse failed — clipboard content is not a supported graph format
    }
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  onMounted(() => {
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keyup', onKeyUp)
  })

  return { spaceHeld }
}
