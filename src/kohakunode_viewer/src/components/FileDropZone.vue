<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";
import { detectAndParseAsync } from "../parser/index.js";

const emit = defineEmits([
  /**
   * Emitted when a file or pasted text is successfully parsed.
   * Payload: { nodes, edges, filename? }
   */
  "graph-loaded",
]);

// ── Drag-over overlay visibility ──────────────────────────────────────────────
const isDragOver = ref(false);
// Counter-based guard so dragging over child elements doesn't flicker the overlay
let dragCounter = 0;

function onDragEnter(e) {
  e.preventDefault();
  dragCounter++;
  isDragOver.value = true;
}

function onDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
}

function onDragLeave() {
  dragCounter--;
  if (dragCounter <= 0) {
    dragCounter = 0;
    isDragOver.value = false;
  }
}

async function onDrop(e) {
  e.preventDefault();
  isDragOver.value = false;
  dragCounter = 0;

  const files = e.dataTransfer?.files;
  if (files && files.length > 0) {
    await loadFile(files[0]);
    return;
  }

  // Fallback: plain text dragged in (e.g. from a text editor)
  const text = e.dataTransfer?.getData("text/plain");
  if (text) {
    loadText("drop.kir", text);
  }
}

// ── File reading ──────────────────────────────────────────────────────────────
async function loadFile(file) {
  const name = file.name;
  const lower = name.toLowerCase();
  if (!lower.endsWith(".kir") && !lower.endsWith(".kirgraph") && !lower.endsWith(".json")) {
    console.warn(`[FileDropZone] Unsupported file type: ${name}`);
    return;
  }
  try {
    const text = await file.text();
    loadText(name, text);
  } catch (err) {
    console.error("[FileDropZone] Failed to read file:", err);
  }
}

async function loadText(filename, text) {
  try {
    const { nodes, edges } = await detectAndParseAsync(text, filename);
    emit("graph-loaded", { nodes, edges, filename });
  } catch (err) {
    console.error("[FileDropZone] Failed to parse content:", err);
  }
}

// ── Paste handler (Ctrl+V anywhere on the page) ───────────────────────────────
async function onPaste(e) {
  // Only handle if no text input is focused (don't steal paste from dialogs/textareas)
  const active = document.activeElement;
  if (
    active &&
    (active.tagName === "INPUT" ||
      active.tagName === "TEXTAREA" ||
      active.isContentEditable)
  ) {
    return;
  }

  const text = e.clipboardData?.getData("text/plain");
  if (!text) return;
  e.preventDefault();
  loadText("paste.kir", text.trim());
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  // Attach drop listeners to the whole document so the drop zone is truly
  // full-screen even when hovering over child components.
  document.addEventListener("dragenter", onDragEnter);
  document.addEventListener("dragover", onDragOver);
  document.addEventListener("dragleave", onDragLeave);
  document.addEventListener("drop", onDrop);
  document.addEventListener("paste", onPaste);
});

onBeforeUnmount(() => {
  document.removeEventListener("dragenter", onDragEnter);
  document.removeEventListener("dragover", onDragOver);
  document.removeEventListener("dragleave", onDragLeave);
  document.removeEventListener("drop", onDrop);
  document.removeEventListener("paste", onPaste);
});
</script>

<template>
  <!-- The component itself renders nothing normally.
       When a file is dragged over the window the full-screen overlay appears. -->
  <Transition name="drop-fade">
    <div v-if="isDragOver" class="drop-overlay">
      <div class="drop-box">
        <div class="drop-icon">&#8681;</div>
        <div class="drop-title">Drop file here</div>
        <div class="drop-hint">.kir &nbsp;·&nbsp; .kirgraph &nbsp;·&nbsp; .json</div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* ── Full-screen drop overlay ── */
.drop-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(17, 17, 27, 0.82);
  backdrop-filter: blur(4px);
  pointer-events: none; /* let the drop event pass through to the document listener */
}

.drop-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 48px 64px;
  border: 2px dashed #89b4fa;
  border-radius: 16px;
  background: rgba(30, 30, 46, 0.7);
}

.drop-icon {
  font-size: 56px;
  color: #89b4fa;
  line-height: 1;
  animation: bounce 0.8s ease-in-out infinite alternate;
}

@keyframes bounce {
  from { transform: translateY(0); }
  to   { transform: translateY(-8px); }
}

.drop-title {
  font-size: 20px;
  font-weight: 700;
  color: #cdd6f4;
}

.drop-hint {
  font-size: 13px;
  color: #6c7086;
  letter-spacing: 0.04em;
}

/* ── Transition ── */
.drop-fade-enter-active,
.drop-fade-leave-active {
  transition: opacity 0.15s ease;
}
.drop-fade-enter-from,
.drop-fade-leave-to {
  opacity: 0;
}
</style>
