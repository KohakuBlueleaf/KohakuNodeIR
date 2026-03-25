import { ref, onMounted, onUnmounted } from "vue";
import { useGraphStore } from "../stores/graph.js";
import { useEditorStore } from "../stores/editor.js";

/**
 * useWireDraw
 *
 * Attach to the editor canvas element.  Port elements must carry these
 * data attributes so the composable can identify them:
 *
 *   data-port-id       — unique port identifier
 *   data-node-id       — owning node id
 *   data-port-type     — "data" | "control"
 *   data-port-dir      — "output" | "input"
 *
 * The composable emits port positions via getBoundingClientRect, so ports
 * must be visible DOM elements.  The caller is responsible for converting
 * draftWire screen coords to canvas coords for rendering if needed.
 */
export function useWireDraw(canvasRef, screenToCanvas) {
  const graphStore = useGraphStore();
  const editorStore = useEditorStore();

  const isDrawing = ref(false);

  // draftWire holds screen-space coordinates for the in-progress wire.
  // Components rendering the wire overlay should use these directly or
  // transform them as needed.
  const draftWire = ref(null);
  // {
  //   fromNodeId, fromPortId,
  //   fromX, fromY,   — canvas-space origin (center of source port)
  //   toX, toY,       — canvas-space cursor position
  //   portType,       — "data" | "control"
  // }

  // Internal state
  let sourcePort = null; // { nodeId, portId, portType, portDir }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /**
   * Given a MouseEvent, walk up the DOM to find the nearest element that has
   * data-port-id.  Returns that element or null.
   */
  function findPortElement(e) {
    let el = e.target;
    while (el && el !== canvasRef.value) {
      if (el.dataset && el.dataset.portId) return el;
      el = el.parentElement;
    }
    return null;
  }

  /**
   * Return canvas-space center of a port DOM element.
   */
  function portCenter(portEl) {
    const rect = portEl.getBoundingClientRect();
    const screenX = rect.left + rect.width / 2;
    const screenY = rect.top + rect.height / 2;
    if (typeof screenToCanvas === "function") {
      return screenToCanvas(screenX, screenY);
    }
    return { x: screenX, y: screenY };
  }

  /**
   * Convert a mouse event's client position to canvas space.
   */
  function mouseToCanvas(e) {
    if (typeof screenToCanvas === "function") {
      return screenToCanvas(e.clientX, e.clientY);
    }
    return { x: e.clientX, y: e.clientY };
  }

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  function isCompatible(src, dst) {
    // Must connect output -> input
    if (src.portDir !== "output" || dst.portDir !== "input") return false;
    // Must match port type
    if (src.portType !== dst.portType) return false;
    // Cannot connect a node to itself
    if (src.nodeId === dst.nodeId) return false;
    return true;
  }

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function onMouseDown(e) {
    if (e.button !== 0) return;

    const portEl = findPortElement(e);
    if (!portEl) return;

    const { portId, nodeId, portType, portDir } = portEl.dataset;

    // Only start drawing from output ports
    if (portDir !== "output") return;

    e.stopPropagation();
    e.preventDefault();

    sourcePort = { portId, nodeId, portType, portDir };

    const origin = portCenter(portEl);
    const cursor = mouseToCanvas(e);

    draftWire.value = {
      fromNodeId: nodeId,
      fromPortId: portId,
      fromX: origin.x,
      fromY: origin.y,
      toX: cursor.x,
      toY: cursor.y,
      portType,
    };

    isDrawing.value = true;

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }

  function onMouseMove(e) {
    if (!isDrawing.value || !draftWire.value) return;
    const pos = mouseToCanvas(e);
    draftWire.value = { ...draftWire.value, toX: pos.x, toY: pos.y };
  }

  function onMouseUp(e) {
    if (!isDrawing.value) return;

    const portEl = findPortElement(e);

    if (portEl) {
      const { portId, nodeId, portType, portDir } = portEl.dataset;
      const destPort = { portId, nodeId, portType, portDir };

      if (isCompatible(sourcePort, destPort)) {
        graphStore.addConnection(
          sourcePort.nodeId,
          sourcePort.portId,
          destPort.nodeId,
          destPort.portId,
          sourcePort.portType,
        );
      }
    }

    cancelDraw();
  }

  function cancelDraw() {
    isDrawing.value = false;
    draftWire.value = null;
    sourcePort = null;
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  onMounted(() => {
    const el = canvasRef.value;
    if (!el) return;
    el.addEventListener("mousedown", onMouseDown);
  });

  onUnmounted(() => {
    const el = canvasRef.value;
    if (el) el.removeEventListener("mousedown", onMouseDown);
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
  });

  return {
    isDrawing,
    draftWire,
    cancelDraw,
  };
}
