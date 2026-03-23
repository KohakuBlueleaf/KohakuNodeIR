import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useGraphStore } from '../stores/graph.js'
import { useEditorStore } from '../stores/editor.js'

/**
 * useSelection
 *
 * Manages node selection on the editor canvas.
 *
 * The canvasRef must be the element that acts as the backdrop (receives
 * mousedown events when no node is clicked).
 *
 * Node elements must carry:
 *   data-node-id   — the node's id
 *
 * screenToCanvas — optional function (screenX, screenY) => { x, y }
 *                  provided by usePanZoom so that the box-select rect is
 *                  expressed in canvas space for intersection testing.
 */
export function useSelection(canvasRef, screenToCanvas) {
  const graphStore = useGraphStore()
  const editorStore = useEditorStore()

  // Box selection state
  const isSelecting = ref(false)

  // selectionBox is in canvas space: { x, y, width, height }
  const selectionBox = ref(null)

  // Raw screen-space anchor (where the drag started)
  let boxStartScreen = { x: 0, y: 0 }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function toCanvas(screenX, screenY) {
    if (typeof screenToCanvas === 'function') return screenToCanvas(screenX, screenY)
    return { x: screenX, y: screenY }
  }

  /**
   * Walk up the DOM from the event target to find an element with data-node-id.
   * Returns the id string or null.
   */
  function findNodeId(e) {
    let el = e.target
    while (el && el !== canvasRef.value) {
      if (el.dataset && el.dataset.nodeId) return el.dataset.nodeId
      el = el.parentElement
    }
    return null
  }

  /**
   * Return a normalised rect { x, y, width, height } for the selection box
   * given two canvas-space corners.
   */
  function normaliseRect(ax, ay, bx, by) {
    return {
      x: Math.min(ax, bx),
      y: Math.min(ay, by),
      width: Math.abs(bx - ax),
      height: Math.abs(by - ay),
    }
  }

  /**
   * Test whether a node's bounding rect intersects a selection rect.
   * Both are in canvas space.
   */
  function nodeIntersectsBox(node, box) {
    const nRight  = node.x + (node.width  ?? 200)
    const nBottom = node.y + (node.height ?? 100)
    const bRight  = box.x + box.width
    const bBottom = box.y + box.height

    return (
      node.x  < bRight  &&
      nRight  > box.x   &&
      node.y  < bBottom &&
      nBottom > box.y
    )
  }

  // ---------------------------------------------------------------------------
  // Node click selection (called by child node components via the canvas
  // mousedown handler by inspecting the event target)
  // ---------------------------------------------------------------------------

  function onMouseDown(e) {
    // Ignore non-left clicks
    if (e.button !== 0) return

    // Ignore if space-pan is active
    if (editorStore.isSpacePanActive) return

    const nodeId = findNodeId(e)

    if (nodeId) {
      // ----- Clicking on a node -----
      // If the node is already selected and Shift is NOT held, just keep
      // selection as-is so that a drag can move the whole selection.
      // A full click (no movement) will refine selection on mouseup.
      if (e.shiftKey) {
        // Toggle this node in the selection
        editorStore.toggleNodeSelection(nodeId)
      } else if (!editorStore.selectedNodeIds.includes(nodeId)) {
        // Select only this node
        editorStore.setSelection([nodeId])
      }
      // Stop propagation so the canvas background handler doesn't fire
      e.stopPropagation()
    } else {
      // ----- Clicking on the canvas background -----
      // Clear selection unless Shift is held (user may be extending a box)
      if (!e.shiftKey) {
        editorStore.setSelection([])
      }

      // Begin box select
      const canvasOrigin = toCanvas(e.clientX, e.clientY)
      boxStartScreen = { x: e.clientX, y: e.clientY }

      selectionBox.value = { x: canvasOrigin.x, y: canvasOrigin.y, width: 0, height: 0 }
      isSelecting.value = true

      window.addEventListener('mousemove', onMouseMoveBox)
      window.addEventListener('mouseup', onMouseUpBox)
    }
  }

  // ---------------------------------------------------------------------------
  // Box select — mouse move
  // ---------------------------------------------------------------------------

  function onMouseMoveBox(e) {
    if (!isSelecting.value) return

    const anchor = toCanvas(boxStartScreen.x, boxStartScreen.y)
    const current = toCanvas(e.clientX, e.clientY)

    selectionBox.value = normaliseRect(anchor.x, anchor.y, current.x, current.y)

    // Live-highlight nodes that fall inside the box
    const ids = graphStore.nodes
      .filter((n) => nodeIntersectsBox(n, selectionBox.value))
      .map((n) => n.id)

    editorStore.setSelection(ids)
  }

  // ---------------------------------------------------------------------------
  // Box select — mouse up
  // ---------------------------------------------------------------------------

  function onMouseUpBox() {
    if (!isSelecting.value) return
    isSelecting.value = false
    selectionBox.value = null

    window.removeEventListener('mousemove', onMouseMoveBox)
    window.removeEventListener('mouseup', onMouseUpBox)
  }

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts handled here (Delete + Ctrl+A)
  // The remaining shortcuts (undo/redo, escape) live in useKeyboard.
  // ---------------------------------------------------------------------------

  function onKeyDown(e) {
    const tag = document.activeElement?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return

    if (e.key === 'Delete' || e.key === 'Backspace') {
      deleteSelected()
    } else if (e.key === 'a' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      editorStore.setSelection(graphStore.nodes.map((n) => n.id))
    }
  }

  function deleteSelected() {
    const ids = editorStore.selectedNodeIds ?? []
    for (const id of ids) {
      graphStore.removeNode(id)
    }
    editorStore.setSelection([])
  }

  // ---------------------------------------------------------------------------
  // Public method: cancel box select (called by useKeyboard on Escape)
  // ---------------------------------------------------------------------------

  function cancelSelection() {
    isSelecting.value = false
    selectionBox.value = null
    window.removeEventListener('mousemove', onMouseMoveBox)
    window.removeEventListener('mouseup', onMouseUpBox)
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  onMounted(() => {
    const el = canvasRef.value
    if (el) el.addEventListener('mousedown', onMouseDown)
    window.addEventListener('keydown', onKeyDown)
  })

  onUnmounted(() => {
    const el = canvasRef.value
    if (el) el.removeEventListener('mousedown', onMouseDown)
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('mousemove', onMouseMoveBox)
    window.removeEventListener('mouseup', onMouseUpBox)
  })

  return {
    selectionBox,
    isSelecting,
    cancelSelection,
    deleteSelected,
  }
}
