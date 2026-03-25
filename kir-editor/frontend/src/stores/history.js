import { ref, computed } from "vue";
import { defineStore } from "pinia";
import { useGraphStore } from "./graph.js";

const MAX_HISTORY = 50;

export const useHistoryStore = defineStore("history", () => {
  // ---- State ----

  /** @type {import('vue').Ref<string[]>} JSON-serialized graph snapshots */
  const undoStack = ref([]);

  /** @type {import('vue').Ref<string[]>} */
  const redoStack = ref([]);

  // ---- Computed ----
  const canUndo = computed(() => undoStack.value.length > 0);
  const canRedo = computed(() => redoStack.value.length > 0);

  // ---- Helpers ----

  /**
   * Take a JSON snapshot of the current graph state.
   * @returns {string}
   */
  function _snapshot() {
    const graph = useGraphStore();
    return JSON.stringify(graph.serialize());
  }

  /**
   * Apply a JSON snapshot to the graph store.
   * @param {string} json
   */
  function _restore(json) {
    const graph = useGraphStore();
    graph.deserialize(JSON.parse(json));
  }

  // ---- Public API ----

  /**
   * Push the current graph state onto the undo stack.
   * Call this BEFORE making a mutation so the previous state is saved.
   * Clears the redo stack (new branch in history).
   */
  function pushState() {
    const snap = _snapshot();

    // Avoid pushing duplicate snapshots
    if (
      undoStack.value.length > 0 &&
      undoStack.value[undoStack.value.length - 1] === snap
    ) {
      return;
    }

    undoStack.value.push(snap);

    // Enforce max history size by dropping the oldest entry
    if (undoStack.value.length > MAX_HISTORY) {
      undoStack.value.shift();
    }

    // A new action invalidates the redo branch
    redoStack.value = [];
  }

  /**
   * Undo the last recorded action.
   * Saves the current state to the redo stack before restoring.
   */
  function undo() {
    if (!canUndo.value) return;

    // Save current state so it can be re-done
    redoStack.value.push(_snapshot());

    const previous = undoStack.value.pop();
    _restore(previous);
  }

  /**
   * Redo the last undone action.
   * Saves the current state to the undo stack before restoring.
   */
  function redo() {
    if (!canRedo.value) return;

    // Save current state so it can be un-done again
    undoStack.value.push(_snapshot());

    const next = redoStack.value.pop();
    _restore(next);
  }

  /**
   * Clear both stacks (e.g. when loading a new graph).
   */
  function clearHistory() {
    undoStack.value = [];
    redoStack.value = [];
  }

  return {
    undoStack,
    redoStack,
    canUndo,
    canRedo,
    pushState,
    undo,
    redo,
    clearHistory,
  };
});
