/**
 * Pyodide-based KIR parser.
 *
 * Loads the real kohakunode Python package in WASM via Pyodide.
 * The Python source files are served from /pylib/kohakunode/.
 *
 * Usage:
 *   const { initPyodide, parseKirWithPython } = await import('./pyodideParser.js')
 *   await initPyodide()
 *   const { nodes, edges } = await parseKirWithPython(kirText)
 */

const PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.27.1/full/pyodide.js";

let pyodide = null;
let ready = false;
let loading = null;

/**
 * Initialize Pyodide, install lark, mount kohakunode source.
 */
export async function initPyodide(onProgress) {
  if (ready) return true;
  if (loading) return loading;

  loading = (async () => {
    try {
      onProgress?.("Loading Pyodide runtime...");

      // Load Pyodide script
      if (!window.loadPyodide) {
        await new Promise((resolve, reject) => {
          const s = document.createElement("script");
          s.src = PYODIDE_CDN;
          s.onload = resolve;
          s.onerror = () => reject(new Error("Failed to load Pyodide CDN"));
          document.head.appendChild(s);
        });
      }

      pyodide = await window.loadPyodide();
      onProgress?.("Installing lark parser...");

      await pyodide.loadPackage("micropip");
      await pyodide.runPythonAsync(`
import micropip
await micropip.install("lark")
`);

      onProgress?.("Loading kohakunode...");

      // Fetch the file manifest and mount all Python files
      await mountKohakunode();

      // Verify import works
      await pyodide.runPythonAsync(`
import kohakunode
print(f"[Pyodide] kohakunode loaded, version={kohakunode.__version__}")
`);

      ready = true;
      onProgress?.("Ready");
      return true;
    } catch (err) {
      console.error("[pyodideParser] Init failed:", err);
      onProgress?.(`Error: ${err.message}`);
      return false;
    }
  })();

  return loading;
}

/**
 * Fetch and mount all kohakunode Python source files into Pyodide's FS.
 */
async function mountKohakunode() {
  // Fetch the manifest (list of files to mount)
  const manifestRes = await fetch("/pylib/manifest.json");
  if (!manifestRes.ok) {
    throw new Error("Could not fetch /pylib/manifest.json — run prebuild first");
  }
  const manifest = await manifestRes.json();

  // Find site-packages path
  const sitePackages = pyodide.runPython("import site; site.getsitepackages()[0]");
  console.log(`[pyodideParser] site-packages: ${sitePackages}`);

  // Create directories and write files
  for (const relPath of manifest.files) {
    const url = `/pylib/${relPath}`;
    const res = await fetch(url);
    if (!res.ok) {
      console.warn(`[pyodideParser] Failed to fetch ${url}`);
      continue;
    }
    const content = await res.text();

    // Ensure parent directories exist
    const parts = relPath.split("/");
    let dir = sitePackages;
    for (let i = 0; i < parts.length - 1; i++) {
      dir += "/" + parts[i];
      try { pyodide.FS.mkdir(dir); } catch { /* exists */ }
    }

    const fullPath = dir + "/" + parts[parts.length - 1];
    pyodide.FS.writeFile(fullPath, content);
  }

  console.log(`[pyodideParser] Mounted ${manifest.files.length} files`);
}

/**
 * Parse KIR text using Python. Returns { nodes, edges } or null on failure.
 */
export async function parseKirWithPython(kirText) {
  if (!ready) {
    const ok = await initPyodide();
    if (!ok) return null;
  }

  try {
    // Use globals to pass data (avoids string escaping issues)
    pyodide.globals.set("_kir_input", kirText);

    const resultJson = await pyodide.runPythonAsync(`
import json
from kohakunode.layout.ascii_view import kir_to_graph
from kohakunode.layout.auto_layout import auto_layout

_graph = kir_to_graph(_kir_input)
_graph = auto_layout(_graph)

_result = {
    "nodes": [{
        "id": n.id,
        "type": n.type,
        "name": n.name,
        "x": n.meta.get("pos", [0, 0])[0],
        "y": n.meta.get("pos", [0, 0])[1],
        "width": n.meta.get("size", [180, 100])[0],
        "height": n.meta.get("size", [180, 100])[1],
        "dataInputs": [{"name": p.port, "type": p.type} for p in n.data_inputs],
        "dataOutputs": [{"name": p.port, "type": p.type} for p in n.data_outputs],
        "ctrlInputs": n.ctrl_inputs,
        "ctrlOutputs": n.ctrl_outputs,
    } for n in _graph.nodes],
    "edges": [{
        "type": e.type,
        "fromNode": e.from_node,
        "fromPort": e.from_port,
        "toNode": e.to_node,
        "toPort": e.to_port,
    } for e in _graph.edges],
}
json.dumps(_result)
`);

    return JSON.parse(resultJson);
  } catch (err) {
    console.error("[pyodideParser] Parse error:", err);
    return null;
  }
}

export function isPyodideReady() {
  return ready;
}
