import { ref, onMounted, onUnmounted } from 'vue'
import { useGraphStore } from '../stores/graph.js'
import { useEditorStore } from '../stores/editor.js'
import { snapPoint } from '../utils/grid.js'

export function useDrag(nodeId, elementRef, getCurrentZoom) {
  const graphStore = useGraphStore()
  const editorStore = useEditorStore()

  const isDragging = ref(false)

  // Positions at the start of the drag for every node being moved
  // Map<nodeId, { x, y }>
  let startPositions = new Map()
  let startMouseX = 0
  let startMouseY = 0

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function getZoom() {
    return typeof getCurrentZoom === 'function' ? getCurrentZoom() : 1
  }

  // ---------------------------------------------------------------------------
  // Drag start — attached to the node header element
  // ---------------------------------------------------------------------------

  function onMouseDown(e) {
    // Only respond to left-mouse-button clicks on the header
    if (e.button !== 0) return

    // Don't start dragging if space is held (that's reserved for pan)
    if (editorStore.isSpacePanActive) return

    e.stopPropagation()
    e.preventDefault()

    const zoom = getZoom()
    startMouseX = e.clientX / zoom
    startMouseY = e.clientY / zoom

    // Determine which nodes will move
    const selection = editorStore.selectedNodeIds ?? []
    const movingIds = selection.includes(nodeId)
      ? selection
      : [nodeId]

    // Snapshot starting positions
    startPositions = new Map()
    for (const id of movingIds) {
      const node = graphStore.getNodeById(id)
      if (node) {
        startPositions.set(id, { x: node.x, y: node.y })
      }
    }

    isDragging.value = true

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  // ---------------------------------------------------------------------------
  // Drag move
  // ---------------------------------------------------------------------------

  function onMouseMove(e) {
    if (!isDragging.value) return

    const zoom = getZoom()
    const currentMouseX = e.clientX / zoom
    const currentMouseY = e.clientY / zoom

    const rawDx = currentMouseX - startMouseX
    const rawDy = currentMouseY - startMouseY

    for (const [id, startPos] of startPositions) {
      const snapped = snapPoint(startPos.x + rawDx, startPos.y + rawDy)
      graphStore.updateNodePosition(id, snapped.x, snapped.y)
    }
  }

  // ---------------------------------------------------------------------------
  // Drag end
  // ---------------------------------------------------------------------------

  function onMouseUp() {
    if (!isDragging.value) return
    isDragging.value = false
    startPositions.clear()
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }

  // ---------------------------------------------------------------------------
  // Lifecycle — attach the mousedown listener to the header inside the element
  // ---------------------------------------------------------------------------

  onMounted(() => {
    const el = elementRef.value
    if (!el) return

    // Attach to the header child if present, otherwise to the root element
    const header = el.querySelector('.node-header') ?? el
    header.addEventListener('mousedown', onMouseDown)
  })

  onUnmounted(() => {
    const el = elementRef.value
    if (el) {
      const header = el.querySelector('.node-header') ?? el
      header.removeEventListener('mousedown', onMouseDown)
    }
    // Safety cleanup in case drag was in progress
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  })

  return { isDragging }
}
