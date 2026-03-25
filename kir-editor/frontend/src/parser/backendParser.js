/**
 * Backend-assisted KIR parser.
 *
 * Sends .kir text to the Python backend for parsing + layout,
 * gets back kirgraph JSON with correct nodes/edges/positions.
 *
 * Falls back to the JS lite parser if backend is unavailable.
 */

const BACKEND_URL = "http://localhost:48888";

let backendAvailable = null; // null = unknown, true/false = checked

/**
 * Check if the backend is reachable.
 */
export async function checkBackend() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/nodes`, {
      method: "GET",
      signal: AbortSignal.timeout(2000),
    });
    backendAvailable = res.ok;
  } catch {
    backendAvailable = false;
  }
  return backendAvailable;
}

/**
 * Parse KIR text via backend. Returns { nodes, edges } or null if unavailable.
 */
export async function parseKirViaBackend(kirText) {
  if (backendAvailable === null) await checkBackend();
  if (!backendAvailable) return null;

  try {
    const res = await fetch(`${BACKEND_URL}/api/decompile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kir_source: kirText }),
    });

    if (!res.ok) return null;
    const data = await res.json();
    if (!data.kirgraph) return null;

    // Convert kirgraph format to viewer format
    const kg = data.kirgraph;
    const nodes = (kg.nodes || []).map((n) => {
      const pos = n.meta?.pos || [0, 0];
      const size = n.meta?.size || [180, 100];
      return {
        id: n.id,
        type: n.type,
        name: n.name,
        x: pos[0] || 0,
        y: pos[1] || 0,
        width: size[0] || 180,
        height: size[1] || 100,
        dataInputs: (n.data_inputs || []).map((p) => ({
          name: p.port,
          type: p.type || "any",
          default: p.default,
        })),
        dataOutputs: (n.data_outputs || []).map((p) => ({
          name: p.port,
          type: p.type || "any",
        })),
        ctrlInputs: n.ctrl_inputs || [],
        ctrlOutputs: n.ctrl_outputs || [],
      };
    });

    const edges = (kg.edges || []).map((e) => ({
      type: e.type,
      fromNode: e.from_node,
      fromPort: e.from_port,
      toNode: e.to_node,
      toPort: e.to_port,
    }));

    return { nodes, edges, format: "kirgraph-via-backend" };
  } catch {
    return null;
  }
}
