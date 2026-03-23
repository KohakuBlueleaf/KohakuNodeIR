import { ref, onMounted, onUnmounted } from 'vue'
import { useGraphStore } from '../stores/graph.js'
import { snapToGrid, GRID_SIZE } from '../utils/grid.js'

// Minimum node dimensions in pixels (8 × 4 grid units)
const MIN_WIDTH = GRID_SIZE * 8   // 160
const MIN_HEIGHT = GRID_SIZE * 4  // 80

// Which edge(s) are being resized
// 'right' | 'bottom' | 'corner'
let activeHandle = null

export function useResize(nodeId, elementRef, getCurrentZoom) {
  const graphStore = useGraphStore()
  const isResizing = ref(false)

  let startMouseX = 0
  let startMouseY = 0
  let startWidth = 0
  let startHeight = 0

  // ---------------------------------------------------------------------------
  // Helper
  // ---------------------------------------------------------------------------

  function getZoom() {
    return typeof getCurrentZoom === 'function' ? getCurrentZoom() : 1
  }

  // ---------------------------------------------------------------------------
  // Create handle elements and inject them into the node element
  // ---------------------------------------------------------------------------

  function createHandles(el) {
    const handles = [
      { className: 'resize-handle resize-handle--right',  edge: 'right' },
      { className: 'resize-handle resize-handle--bottom', edge: 'bottom' },
      { className: 'resize-handle resize-handle--corner', edge: 'corner' },
    ]

    for (const { className, edge } of handles) {
      // Avoid duplicating handles if composable is called multiple times
      if (el.querySelector(`.resize-handle--${edge}`)) continue

      const handle = document.createElement('div')
      handle.className = className
      handle.dataset.edge = edge

      // Inline positioning styles so the handle works without external CSS
      Object.assign(handle.style, getHandleStyle(edge))

      handle.addEventListener('mousedown', (e) => onHandleMouseDown(e, edge))
      el.appendChild(handle)
    }
  }

  function getHandleStyle(edge) {
    const base = {
      position: 'absolute',
      zIndex: '10',
      userSelect: 'none',
    }
    switch (edge) {
      case 'right':
        return { ...base, top: '0', right: '-4px', width: '8px', height: '100%', cursor: 'ew-resize' }
      case 'bottom':
        return { ...base, bottom: '-4px', left: '0', width: '100%', height: '8px', cursor: 'ns-resize' }
      case 'corner':
        return { ...base, bottom: '-4px', right: '-4px', width: '12px', height: '12px', cursor: 'nwse-resize' }
      default:
        return base
    }
  }

  // ---------------------------------------------------------------------------
  // Mouse down on a resize handle
  // ---------------------------------------------------------------------------

  function onHandleMouseDown(e, edge) {
    if (e.button !== 0) return
    e.stopPropagation()
    e.preventDefault()

    activeHandle = edge

    const zoom = getZoom()
    startMouseX = e.clientX / zoom
    startMouseY = e.clientY / zoom

    const node = graphStore.nodes.get(nodeId)
    if (!node) return
    startWidth = node.width ?? MIN_WIDTH
    startHeight = node.height ?? MIN_HEIGHT

    isResizing.value = true

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  // ---------------------------------------------------------------------------
  // Mouse move
  // ---------------------------------------------------------------------------

  function onMouseMove(e) {
    if (!isResizing.value) return

    const zoom = getZoom()
    const dx = e.clientX / zoom - startMouseX
    const dy = e.clientY / zoom - startMouseY

    let newWidth = startWidth
    let newHeight = startHeight

    if (activeHandle === 'right' || activeHandle === 'corner') {
      newWidth = Math.max(MIN_WIDTH, snapToGrid(startWidth + dx))
    }
    if (activeHandle === 'bottom' || activeHandle === 'corner') {
      newHeight = Math.max(MIN_HEIGHT, snapToGrid(startHeight + dy))
    }

    graphStore.updateNodeSize(nodeId, newWidth, newHeight)
  }

  // ---------------------------------------------------------------------------
  // Mouse up
  // ---------------------------------------------------------------------------

  function onMouseUp() {
    if (!isResizing.value) return
    isResizing.value = false
    activeHandle = null
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  onMounted(() => {
    const el = elementRef.value
    if (!el) return
    createHandles(el)
  })

  onUnmounted(() => {
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  })

  return { isResizing }
}
