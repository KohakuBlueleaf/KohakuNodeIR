import { ref, reactive, computed } from 'vue';
import { defineStore } from 'pinia';
import { useGraphStore } from './graph.js';
import { useHistoryStore } from './history.js';

const ZOOM_MIN = 0.1;
const ZOOM_MAX = 3.0;
const ZOOM_STEP = 0.1;

export const useEditorStore = defineStore('editor', () => {
  // ---- Pan / Zoom ----
  const panX = ref(0);   // canvas origin offset in screen pixels
  const panY = ref(0);
  const zoom = ref(1.0); // scale factor

  // ---- Selection ----
  const selectedNodeIds = reactive(new Set());
  const selectedConnectionIds = reactive(new Set());

  // ---- Interaction ----
  const isDragging = ref(false);
  const isDrawingWire = ref(false);

  /** @type {import('vue').Ref<{fromNodeId:string, fromPortId:string, portType:string, mouseX:number, mouseY:number}|null>} */
  const draftWire = ref(null);

  const isSelecting = ref(false);

  /** @type {import('vue').Ref<{x1:number, y1:number, x2:number, y2:number}|null>} */
  const selectionBox = ref(null);

  // ---- Mode ----
  /** @type {import('vue').Ref<'dataflow'|'controlflow'>} */
  const mode = ref('controlflow');

  // ---- Show/hide control ports ----
  const showCtrlPorts = ref(true);

  // ---- Space-pan state (set by useKeyboard, read by usePanZoom/useSelection) ----
  const isSpacePanActive = ref(false);

  // ---- Computed ----
  const hasSelection = computed(
    () => selectedNodeIds.size > 0 || selectedConnectionIds.size > 0
  );

  // ---- Coordinate Conversion ----

  /**
   * Convert screen-space coordinates to canvas-space coordinates.
   * @param {number} screenX
   * @param {number} screenY
   * @returns {{ x: number, y: number }}
   */
  function screenToCanvas(screenX, screenY) {
    return {
      x: (screenX - panX.value) / zoom.value,
      y: (screenY - panY.value) / zoom.value,
    };
  }

  /**
   * Convert canvas-space coordinates to screen-space coordinates.
   * @param {number} canvasX
   * @param {number} canvasY
   * @returns {{ x: number, y: number }}
   */
  function canvasToScreen(canvasX, canvasY) {
    return {
      x: canvasX * zoom.value + panX.value,
      y: canvasY * zoom.value + panY.value,
    };
  }

  // ---- Pan ----

  /**
   * Set the pan offset directly.
   * @param {number} x
   * @param {number} y
   */
  function setPan(x, y) {
    panX.value = x;
    panY.value = y;
  }

  /**
   * Translate the current pan by a delta.
   * @param {number} dx
   * @param {number} dy
   */
  function pan(dx, dy) {
    panX.value += dx;
    panY.value += dy;
  }

  // ---- Zoom ----

  function zoomIn() {
    zoom.value = Math.min(ZOOM_MAX, parseFloat((zoom.value + ZOOM_STEP).toFixed(2)));
  }

  function zoomOut() {
    zoom.value = Math.max(ZOOM_MIN, parseFloat((zoom.value - ZOOM_STEP).toFixed(2)));
  }

  function resetZoom() {
    zoom.value = 1.0;
    panX.value = 0;
    panY.value = 0;
  }

  /**
   * Zoom toward/away from a focal point in screen space (e.g., mouse position).
   * @param {number} delta   Positive = zoom in, negative = zoom out
   * @param {number} focalX  Screen X of focal point
   * @param {number} focalY  Screen Y of focal point
   */
  function zoomAtPoint(delta, focalX, focalY) {
    const oldZoom = zoom.value;
    const newZoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, parseFloat((oldZoom + delta).toFixed(2))));
    if (newZoom === oldZoom) return;

    // Adjust pan so the focal point stays fixed on screen
    panX.value = focalX - (focalX - panX.value) * (newZoom / oldZoom);
    panY.value = focalY - (focalY - panY.value) * (newZoom / oldZoom);
    zoom.value = newZoom;
  }

  // ---- Selection ----

  /**
   * Select a node. If additive is false, clears existing selection first.
   * @param {string} id
   * @param {boolean} [additive=false]
   */
  function selectNode(id, additive = false) {
    if (!additive) {
      selectedNodeIds.clear();
      selectedConnectionIds.clear();
    }
    selectedNodeIds.add(id);
  }

  /**
   * Select a connection. If additive is false, clears existing selection first.
   * @param {string} id
   * @param {boolean} [additive=false]
   */
  function selectConnection(id, additive = false) {
    if (!additive) {
      selectedNodeIds.clear();
      selectedConnectionIds.clear();
    }
    selectedConnectionIds.add(id);
  }

  /**
   * Toggle node selection.
   * @param {string} id
   */
  function toggleNodeSelection(id) {
    if (selectedNodeIds.has(id)) {
      selectedNodeIds.delete(id);
    } else {
      selectedNodeIds.add(id);
    }
  }

  /**
   * Clear all selections.
   */
  function deselectAll() {
    selectedNodeIds.clear();
    selectedConnectionIds.clear();
  }

  /**
   * Delete all currently selected nodes and connections from the graph store.
   */
  function deleteSelected() {
    const graph = useGraphStore();
    if (selectedConnectionIds.size === 0 && selectedNodeIds.size === 0) return;

    // Push ONE history snapshot before the entire batch
    useHistoryStore().pushState();

    // Delete selected connections first (removing a node already removes its connections)
    for (const connId of selectedConnectionIds) {
      graph.connections.delete(connId);
    }
    selectedConnectionIds.clear();

    // Delete selected nodes and their associated connections
    for (const nodeId of selectedNodeIds) {
      // Remove every connection that touches this node
      for (const [connId, conn] of graph.connections) {
        if (conn.fromNodeId === nodeId || conn.toNodeId === nodeId) {
          graph.connections.delete(connId);
        }
      }
      graph.nodes.delete(nodeId);
    }
    selectedNodeIds.clear();
  }

  // ---- Box Selection ----

  /**
   * Begin a rubber-band selection box.
   * @param {number} x1 Canvas X
   * @param {number} y1 Canvas Y
   */
  function startSelectionBox(x1, y1) {
    isSelecting.value = true;
    selectionBox.value = { x1, y1, x2: x1, y2: y1 };
  }

  /**
   * Update the far corner of the selection box.
   * @param {number} x2
   * @param {number} y2
   */
  function updateSelectionBox(x2, y2) {
    if (!selectionBox.value) return;
    selectionBox.value.x2 = x2;
    selectionBox.value.y2 = y2;
  }

  /**
   * Commit the selection box — select all nodes whose bounds intersect it.
   * @param {boolean} [additive=false]
   */
  function commitSelectionBox(additive = false) {
    if (!selectionBox.value) return;
    const { x1, y1, x2, y2 } = selectionBox.value;
    const minX = Math.min(x1, x2);
    const maxX = Math.max(x1, x2);
    const minY = Math.min(y1, y2);
    const maxY = Math.max(y1, y2);

    const graph = useGraphStore();

    if (!additive) {
      selectedNodeIds.clear();
      selectedConnectionIds.clear();
    }

    for (const node of graph.nodes.values()) {
      const nodeRight = node.x + node.width;
      const nodeBottom = node.y + node.height;
      const overlaps =
        node.x < maxX && nodeRight > minX &&
        node.y < maxY && nodeBottom > minY;
      if (overlaps) {
        selectedNodeIds.add(node.id);
      }
    }

    isSelecting.value = false;
    selectionBox.value = null;
  }

  /**
   * Replace the current node selection with the given array of ids.
   * Clears connection selection too (matches single-item behaviour).
   * @param {string[]} ids
   */
  function setSelection(ids) {
    selectedNodeIds.clear();
    selectedConnectionIds.clear();
    for (const id of ids) selectedNodeIds.add(id);
  }

  /**
   * Activate or deactivate space-pan mode.
   * @param {boolean} active
   */
  function setSpacePanActive(active) {
    isSpacePanActive.value = !!active;
  }

  /**
   * Cancel an in-progress selection box without committing.
   */
  function cancelSelectionBox() {
    isSelecting.value = false;
    selectionBox.value = null;
  }

  // ---- Draft Wire ----

  /**
   * Begin drawing a wire from an output port.
   * @param {string} fromNodeId
   * @param {string} fromPortId
   * @param {'data'|'control'} portType
   */
  function startDraftWire(fromNodeId, fromPortId, portType) {
    const graph = useGraphStore();
    const pos = graph.getPortPosition(fromNodeId, fromPortId) ?? { x: 0, y: 0 };
    isDrawingWire.value = true;
    draftWire.value = {
      fromNodeId,
      fromPortId,
      portType,
      mouseX: pos.x,
      mouseY: pos.y,
    };
  }

  /**
   * Update the free end of the draft wire to the current mouse position.
   * Coordinates should be in canvas space.
   * @param {number} mouseX
   * @param {number} mouseY
   */
  function updateDraftWire(mouseX, mouseY) {
    if (!draftWire.value) return;
    draftWire.value.mouseX = mouseX;
    draftWire.value.mouseY = mouseY;
  }

  /**
   * Finish drawing a wire by connecting it to a target port.
   * Calls graph.addConnection() if the connection is valid.
   * @param {string} toNodeId
   * @param {string} toPortId
   * @returns {string|null} The new connection id, or null if invalid.
   */
  function endDraftWire(toNodeId, toPortId) {
    if (!draftWire.value) return null;
    const { fromNodeId, fromPortId, portType } = draftWire.value;

    isDrawingWire.value = false;
    draftWire.value = null;

    const graph = useGraphStore();
    return graph.addConnection(fromNodeId, fromPortId, toNodeId, toPortId, portType);
  }

  /**
   * Discard the draft wire without creating a connection.
   */
  function cancelDraftWire() {
    isDrawingWire.value = false;
    draftWire.value = null;
  }

  // ---- Mode ----

  /**
   * Switch between 'dataflow' and 'controlflow' modes.
   * @param {'dataflow'|'controlflow'} newMode
   */
  function setMode(newMode) {
    if (newMode === 'dataflow' || newMode === 'controlflow') {
      mode.value = newMode;
    }
  }

  return {
    // Pan / Zoom
    panX,
    panY,
    zoom,
    setPan,
    pan,
    zoomIn,
    zoomOut,
    resetZoom,
    zoomAtPoint,

    // Coordinate conversion
    screenToCanvas,
    canvasToScreen,

    // Selection
    selectedNodeIds,
    selectedConnectionIds,
    hasSelection,
    selectNode,
    selectConnection,
    toggleNodeSelection,
    deselectAll,
    deleteSelected,
    setSelection,

    // Space-pan
    isSpacePanActive,
    setSpacePanActive,

    // Box selection
    isSelecting,
    selectionBox,
    startSelectionBox,
    updateSelectionBox,
    commitSelectionBox,
    cancelSelectionBox,

    // Wire drawing
    isDragging,
    isDrawingWire,
    draftWire,
    startDraftWire,
    updateDraftWire,
    endDraftWire,
    cancelDraftWire,

    // Mode
    mode,
    setMode,

    // Control ports visibility
    showCtrlPorts,
  };
});
