import { ref, onMounted, onUnmounted } from 'vue'
import { useGraphStore } from '../stores/graph.js'
import { useEditorStore } from '../stores/editor.js'
import { useHistoryStore } from '../stores/history.js'
import { detectAndParseAsync } from '../parser/index.js'
import { parserResultToGraph } from '../utils/parserResultToGraph.js'

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

  // parserResultToGraph imported from ../utils/parserResultToGraph.js
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
