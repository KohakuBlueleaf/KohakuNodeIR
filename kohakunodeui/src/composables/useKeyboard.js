import { ref, onMounted, onUnmounted } from 'vue'
import { useGraphStore } from '../stores/graph.js'
import { useEditorStore } from '../stores/editor.js'

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
      editorStore.setSelection(graphStore.nodes.map((n) => n.id))
      return
    }

    // Ctrl+Z — undo
    if (ctrl && !e.shiftKey && e.key === 'z') {
      e.preventDefault()
      graphStore.undo?.()
      return
    }

    // Ctrl+Shift+Z — redo
    if (ctrl && e.shiftKey && e.key === 'z') {
      e.preventDefault()
      graphStore.redo?.()
      return
    }

    // Ctrl+Y — redo (Windows convention)
    if (ctrl && e.key === 'y') {
      e.preventDefault()
      graphStore.redo?.()
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
    const ids = editorStore.selectedNodeIds ?? []
    for (const id of [...ids]) {
      graphStore.removeNode(id)
    }
    editorStore.setSelection([])
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
