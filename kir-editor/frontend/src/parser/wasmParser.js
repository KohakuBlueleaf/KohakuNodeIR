/**
 * WASM-based KIR parser.
 *
 * Replaces the Pyodide-based parser with native Rust compiled to WASM.
 * All functions match the same API surface as the old pyodideParser.js.
 */

import init, {
  parse_kir,
  compile_kirgraph,
  compile_dataflow,
  strip_meta,
  write_kir,
  kir_to_graph,
  auto_layout,
} from "../wasm/kohakunode_rs.js";

let ready = false;
let loading = null;

/**
 * Initialize the WASM module.
 * @param {((msg: string) => void) | undefined} onProgress
 * @returns {Promise<boolean>}
 */
export async function initWasm(onProgress) {
  if (ready) return true;
  if (loading) return loading;

  loading = (async () => {
    try {
      onProgress?.("Loading WASM module...");
      await init();
      ready = true;
      onProgress?.("Ready");
      return true;
    } catch (err) {
      console.error("[wasmParser] Init failed:", err);
      onProgress?.(`Error: ${err.message}`);
      return false;
    }
  })();

  return loading;
}

/**
 * @returns {boolean}
 */
export function isWasmReady() {
  return ready;
}

/** Backward-compat alias. */
export const isPyodideReady = isWasmReady;

/**
 * Convert KirGraph JSON (Rust serde format) to the viewer format
 * that parserResultToGraph expects.
 *
 * KirGraph node: { id, type, name, data_inputs: [{port,type,default?}], data_outputs, ctrl_inputs: [str], ctrl_outputs, properties, meta }
 * Viewer node:   { id, type, name, x, y, width, height, dataInputs: [{name,type,default?}], dataOutputs, ctrlInputs: [str], ctrlOutputs, properties }
 *
 * KirGraph edge: { type, from: {node,port}, to: {node,port} }
 * Viewer edge:   { type, fromNode, fromPort, toNode, toPort }
 */
function kirgraphToViewer(kg) {
  const nodes = (kg.nodes ?? []).map((n) => {
    const meta = n.meta ?? {};
    const pos = meta.pos ?? [0, 0];
    const size = meta.size ?? [180, 100];
    // pos/size can be Value arrays — extract numbers
    const x = Array.isArray(pos) ? (pos[0] ?? 0) : 0;
    const y = Array.isArray(pos) ? (pos[1] ?? 0) : 0;
    const width = Array.isArray(size) ? (size[0] ?? 180) : 180;
    const height = Array.isArray(size) ? (size[1] ?? 100) : 100;

    return {
      id: n.id,
      type: n.type,
      name: n.name,
      x,
      y,
      width,
      height,
      dataInputs: (n.data_inputs ?? []).map((p) => {
        const o = { name: p.port, type: p.type ?? "any" };
        if (p.default != null) o.default = p.default;
        return o;
      }),
      dataOutputs: (n.data_outputs ?? []).map((p) => ({
        name: p.port,
        type: p.type ?? "any",
      })),
      ctrlInputs: n.ctrl_inputs ?? [],
      ctrlOutputs: n.ctrl_outputs ?? [],
      ...(n.properties && Object.keys(n.properties).length
        ? { properties: n.properties }
        : {}),
    };
  });

  const edges = (kg.edges ?? []).map((e) => ({
    type: e.type,
    fromNode: e.from?.node ?? "",
    fromPort: e.from?.port ?? "",
    toNode: e.to?.node ?? "",
    toPort: e.to?.port ?? "",
  }));

  return { nodes, edges };
}

/**
 * Parse KIR text and return { nodes, edges } for the graph viewer.
 * Uses kir_to_graph + auto_layout from the WASM module.
 *
 * @param {string} kirText
 * @returns {Promise<{ nodes: object[], edges: object[] } | null>}
 */
export async function parseKirWithWasm(kirText) {
  if (!ready) {
    const ok = await initWasm();
    if (!ok) return null;
  }

  try {
    const graphJson = kir_to_graph(kirText);
    const laidOut = auto_layout(graphJson);
    const kg = JSON.parse(laidOut);
    return kirgraphToViewer(kg);
  } catch (err) {
    console.error("[wasmParser] Parse error:", err);
    return null;
  }
}

/**
 * Compile a .kirgraph JSON string to L2 KIR text.
 *
 * @param {string} kirgraphJson
 * @returns {Promise<string | null>}
 */
export async function compileGraphToKir(kirgraphJson) {
  if (!ready) {
    const ok = await initWasm();
    if (!ok) return null;
  }

  try {
    const programJson = compile_kirgraph(kirgraphJson);
    return write_kir(programJson);
  } catch (err) {
    console.error("[wasmParser] compileGraphToKir error:", err);
    return null;
  }
}

/**
 * Compile a .kirgraph JSON string to L3 KIR text (with dataflow + strip_meta).
 *
 * @param {string} kirgraphJson
 * @returns {Promise<string | null>}
 */
export async function compileGraphToKirL3(kirgraphJson) {
  if (!ready) {
    const ok = await initWasm();
    if (!ok) return null;
  }

  try {
    let programJson = compile_kirgraph(kirgraphJson);
    programJson = compile_dataflow(programJson);
    programJson = strip_meta(programJson);
    return write_kir(programJson);
  } catch (err) {
    console.error("[wasmParser] compileGraphToKirL3 error:", err);
    return null;
  }
}

/**
 * Parse KIR text and return the AST as a plain JS object.
 *
 * @param {string} kirText
 * @returns {Promise<object | null>}
 */
export async function parseKirToAst(kirText) {
  if (!ready) {
    const ok = await initWasm();
    if (!ok) return null;
  }

  try {
    const astJson = parse_kir(kirText);
    return JSON.parse(astJson);
  } catch (err) {
    console.error("[wasmParser] parseKirToAst error:", err);
    return null;
  }
}
