import { ref, onMounted, onUnmounted } from 'vue'

const MIN_ZOOM = 0.1
const MAX_ZOOM = 3.0
const DEFAULT_ZOOM = 1.0

export function usePanZoom(containerRef) {
  const panX = ref(0)
  const panY = ref(0)
  const zoom = ref(DEFAULT_ZOOM)

  // Internal state — not reactive, used only inside event handlers
  let isPanning = false
  let spaceHeld = false
  let lastMouseX = 0
  let lastMouseY = 0
  // For pinch-to-zoom on trackpad
  let lastPinchDist = null

  // ---------------------------------------------------------------------------
  // Coordinate helpers
  // ---------------------------------------------------------------------------

  function screenToCanvas(screenX, screenY) {
    return {
      x: (screenX - panX.value) / zoom.value,
      y: (screenY - panY.value) / zoom.value,
    }
  }

  function canvasToScreen(canvasX, canvasY) {
    return {
      x: canvasX * zoom.value + panX.value,
      y: canvasY * zoom.value + panY.value,
    }
  }

  // ---------------------------------------------------------------------------
  // Zoom toward a screen-space point
  // ---------------------------------------------------------------------------

  function applyZoom(newZoom, originX, originY) {
    const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, newZoom))
    // Keep the canvas point under the cursor stationary:
    //   panX' = originX - canvasX * clamped
    const canvasX = (originX - panX.value) / zoom.value
    const canvasY = (originY - panY.value) / zoom.value
    zoom.value = clamped
    panX.value = originX - canvasX * clamped
    panY.value = originY - canvasY * clamped
  }

  // ---------------------------------------------------------------------------
  // Reset
  // ---------------------------------------------------------------------------

  function resetView() {
    panX.value = 0
    panY.value = 0
    zoom.value = DEFAULT_ZOOM
  }

  // ---------------------------------------------------------------------------
  // Keyboard handlers (space for pan mode)
  // ---------------------------------------------------------------------------

  function onKeyDown(e) {
    if (e.code === 'Space' && !e.repeat) {
      // Only activate if focus isn't on an input/textarea
      if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return
      spaceHeld = true
      const el = containerRef.value
      if (el) el.style.cursor = 'grab'
      e.preventDefault()
    }
  }

  function onKeyUp(e) {
    if (e.code === 'Space') {
      spaceHeld = false
      isPanning = false
      const el = containerRef.value
      if (el) el.style.cursor = ''
    }
  }

  // ---------------------------------------------------------------------------
  // Mouse handlers
  // ---------------------------------------------------------------------------

  function onMouseDown(e) {
    const isMiddle = e.button === 1
    const isSpacePan = spaceHeld && e.button === 0

    if (isMiddle || isSpacePan) {
      isPanning = true
      lastMouseX = e.clientX
      lastMouseY = e.clientY
      const el = containerRef.value
      if (el) el.style.cursor = 'grabbing'
      e.preventDefault()
    }
  }

  function onMouseMove(e) {
    if (!isPanning) return
    const dx = e.clientX - lastMouseX
    const dy = e.clientY - lastMouseY
    panX.value += dx
    panY.value += dy
    lastMouseX = e.clientX
    lastMouseY = e.clientY
  }

  function onMouseUp(e) {
    if (isPanning) {
      isPanning = false
      const el = containerRef.value
      if (el) el.style.cursor = spaceHeld ? 'grab' : ''
    }
    // Release middle mouse
    if (e.button === 1) e.preventDefault()
  }

  // ---------------------------------------------------------------------------
  // Wheel handler — zoom or pan via trackpad two-finger scroll
  // ---------------------------------------------------------------------------

  function onWheel(e) {
    e.preventDefault()

    // Distinguish pinch gesture (ctrlKey is set by browsers for pinch-to-zoom)
    // and two-finger pan (deltaX + deltaY without ctrlKey)
    if (e.ctrlKey) {
      // Pinch-to-zoom or Ctrl+wheel
      const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92
      const rect = containerRef.value ? containerRef.value.getBoundingClientRect() : { left: 0, top: 0 }
      const originX = e.clientX - rect.left
      const originY = e.clientY - rect.top
      applyZoom(zoom.value * zoomFactor, originX, originY)
    } else if (e.deltaMode === WheelEvent.DOM_DELTA_PIXEL) {
      // Normal mouse wheel or two-finger trackpad scroll
      // Use deltaY for zoom when it looks like a scroll wheel (large discrete steps)
      // and for pan when it looks like a trackpad (small continuous values)
      const isTrackpadScroll = Math.abs(e.deltaY) < 50 && e.deltaMode === 0

      if (isTrackpadScroll) {
        // Two-finger trackpad pan
        panX.value -= e.deltaX
        panY.value -= e.deltaY
      } else {
        // Mouse wheel zoom
        const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9
        const rect = containerRef.value ? containerRef.value.getBoundingClientRect() : { left: 0, top: 0 }
        const originX = e.clientX - rect.left
        const originY = e.clientY - rect.top
        applyZoom(zoom.value * zoomFactor, originX, originY)
      }
    } else {
      // DOM_DELTA_LINE or DOM_DELTA_PAGE — treat as zoom
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9
      const rect = containerRef.value ? containerRef.value.getBoundingClientRect() : { left: 0, top: 0 }
      const originX = e.clientX - rect.left
      const originY = e.clientY - rect.top
      applyZoom(zoom.value * zoomFactor, originX, originY)
    }
  }

  // ---------------------------------------------------------------------------
  // Touch handlers for pinch-to-zoom
  // ---------------------------------------------------------------------------

  function getTouchDist(touches) {
    const dx = touches[0].clientX - touches[1].clientX
    const dy = touches[0].clientY - touches[1].clientY
    return Math.sqrt(dx * dx + dy * dy)
  }

  function getTouchMidpoint(touches) {
    return {
      x: (touches[0].clientX + touches[1].clientX) / 2,
      y: (touches[0].clientY + touches[1].clientY) / 2,
    }
  }

  function onTouchStart(e) {
    if (e.touches.length === 2) {
      lastPinchDist = getTouchDist(e.touches)
      e.preventDefault()
    } else if (e.touches.length === 1) {
      isPanning = true
      lastMouseX = e.touches[0].clientX
      lastMouseY = e.touches[0].clientY
    }
  }

  function onTouchMove(e) {
    if (e.touches.length === 2) {
      e.preventDefault()
      const dist = getTouchDist(e.touches)
      if (lastPinchDist !== null) {
        const scaleFactor = dist / lastPinchDist
        const mid = getTouchMidpoint(e.touches)
        const rect = containerRef.value ? containerRef.value.getBoundingClientRect() : { left: 0, top: 0 }
        applyZoom(zoom.value * scaleFactor, mid.x - rect.left, mid.y - rect.top)
      }
      lastPinchDist = dist
    } else if (e.touches.length === 1 && isPanning) {
      const dx = e.touches[0].clientX - lastMouseX
      const dy = e.touches[0].clientY - lastMouseY
      panX.value += dx
      panY.value += dy
      lastMouseX = e.touches[0].clientX
      lastMouseY = e.touches[0].clientY
    }
  }

  function onTouchEnd(e) {
    if (e.touches.length < 2) lastPinchDist = null
    if (e.touches.length === 0) isPanning = false
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  onMounted(() => {
    const el = containerRef.value
    if (!el) return

    el.addEventListener('mousedown', onMouseDown)
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('touchstart', onTouchStart, { passive: false })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd)

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
  })

  onUnmounted(() => {
    const el = containerRef.value
    if (el) {
      el.removeEventListener('mousedown', onMouseDown)
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
    }

    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keyup', onKeyUp)
  })

  return {
    panX,
    panY,
    zoom,
    resetView,
    screenToCanvas,
    canvasToScreen,
  }
}
