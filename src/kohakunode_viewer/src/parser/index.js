/**
 * index.js
 * Auto-detect format and parse any supported graph file into the viewer format.
 *
 * Supported formats:
 *   kirgraph  — .kirgraph JSON  (version + nodes + edges)
 *   comfyui   — ComfyUI workflow JSON (nodes/links) or API JSON (class_type)
 *   kir       — KIR text source (.kir), L2 or L3
 *
 * All parsers return the same shape:
 *   { nodes: [...], edges: [...] }
 *
 * Node shape:
 *   { id, type, name, x, y, width, height,
 *     dataInputs:  [{ name, type, default? }],
 *     dataOutputs: [{ name, type }],
 *     ctrlInputs:  [string],
 *     ctrlOutputs: [string] }
 *
 * Edge shape:
 *   { type: 'data'|'control', fromNode, fromPort, toNode, toPort }
 *
 * detectAndParse() adds a `format` field:
 *   { nodes, edges, format: 'kir' | 'kirgraph' | 'comfyui' | 'unknown' }
 */

import { loadKirgraph } from "./kirgraphLoader.js";
import { parseKirLite } from "./kirLiteParser.js";
import { loadComfyUI } from "./comfyLoader.js";
import { initPyodide, parseKirWithPython, isPyodideReady } from "./pyodideParser.js";

export { loadKirgraph, parseKirLite, loadComfyUI, initPyodide, parseKirWithPython, isPyodideReady };

/**
 * Detect the format of `content` (optionally aided by `filename`) and parse
 * it into the viewer's canonical graph format.
 *
 * Detection order:
 *   1. Filename ends with `.kirgraph`  → kirgraph JSON
 *   2. Filename ends with `.kir`       → KIR text
 *   3. Filename ends with `.json`:
 *        a. Has `version` + `nodes` + `edges` arrays  → kirgraph JSON
 *        b. Has `nodes` array + `links` key           → ComfyUI workflow
 *        c. First value has `class_type`              → ComfyUI API
 *   4. Content sniffing (no filename or unrecognised extension):
 *        a. Starts with `{` or `[` → try JSON (kirgraph, then comfyui)
 *        b. Otherwise              → KIR text
 *
 * @param {string}      content  - Raw file content (string).
 * @param {string|null} filename - Optional filename hint (basename or full path).
 * @returns {{ nodes: object[], edges: object[], format: string }}
 */
export function detectAndParse(content, filename = null) {
  const name = filename ? String(filename) : "";

  // ---- Extension-based detection ----

  if (name.endsWith(".kirgraph")) {
    const json = parseJSON(content, ".kirgraph");
    return { ...loadKirgraph(json), format: "kirgraph" };
  }

  if (name.endsWith(".kir")) {
    return { ...parseKirLite(content), format: "kir" };
  }

  if (name.endsWith(".json")) {
    const json = parseJSON(content, ".json");
    return detectJson(json);
  }

  // ---- Content sniffing (unknown or no extension) ----

  const trimmed = content.trimStart();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const json = JSON.parse(content);
      return detectJson(json);
    } catch {
      // Not valid JSON — fall through to KIR text parser
    }
  }

  // Default: treat as KIR text
  return { ...parseKirLite(content), format: "kir" };
}

/**
 * Async version — tries Pyodide (real Python parser) for .kir files,
 * falls back to JS lite parser.
 */
export async function detectAndParseAsync(content, filename = null) {
  const name = filename ? String(filename) : "";

  // For .kir files, try Pyodide first
  if (name.endsWith(".kir") || (!name.endsWith(".json") && !name.endsWith(".kirgraph") && !content.trimStart().startsWith("{"))) {
    if (isPyodideReady()) {
      const result = await parseKirWithPython(content);
      if (result && result.nodes && result.nodes.length > 0) {
        return { ...result, format: "kir-python" };
      }
    }
  }

  // Fall back to sync parser
  return detectAndParse(content, filename);
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Parse a JSON string, throwing a descriptive error on failure.
 */
function parseJSON(content, context) {
  try {
    return JSON.parse(content);
  } catch (err) {
    throw new Error(`detectAndParse: invalid JSON in ${context} file — ${err.message}`);
  }
}

/**
 * Inspect a parsed JSON object and route to the correct converter.
 * Returns { nodes, edges, format }.
 */
function detectJson(json) {
  if (!json || typeof json !== "object" || Array.isArray(json)) {
    return { nodes: [], edges: [], format: "unknown" };
  }

  // kirgraph: must have version field AND both nodes and edges as arrays
  if (
    json.version !== undefined &&
    Array.isArray(json.nodes) &&
    Array.isArray(json.edges)
  ) {
    return { ...loadKirgraph(json), format: "kirgraph" };
  }

  // ComfyUI workflow: has nodes array + links key (links may be empty array)
  if (Array.isArray(json.nodes) && "links" in json) {
    return { ...loadComfyUI(json), format: "comfyui" };
  }

  // ComfyUI API format: values are objects with class_type
  if (Object.keys(json).length > 0) {
    const firstVal = Object.values(json)[0];
    if (firstVal && typeof firstVal === "object" && "class_type" in firstVal) {
      return { ...loadComfyUI(json), format: "comfyui" };
    }
  }

  // Unknown JSON — return empty graph
  return { nodes: [], edges: [], format: "unknown" };
}
