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

const PYODIDE_CDN = 'https://cdn.jsdelivr.net/pyodide/v0.27.1/full/pyodide.js';

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
      onProgress?.('Loading Pyodide runtime...');

      // Load Pyodide script
      if (!window.loadPyodide) {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = PYODIDE_CDN;
          s.onload = resolve;
          s.onerror = () => reject(new Error('Failed to load Pyodide CDN'));
          document.head.appendChild(s);
        });
      }

      pyodide = await window.loadPyodide();
      onProgress?.('Installing lark parser...');

      await pyodide.loadPackage('micropip');
      await pyodide.runPythonAsync(`
import micropip
await micropip.install("lark")
`);

      onProgress?.('Loading kohakunode...');

      // Fetch the file manifest and mount all Python files
      await mountKohakunode();

      // Verify import works
      await pyodide.runPythonAsync(`
import kohakunode
print(f"[Pyodide] kohakunode loaded, version={kohakunode.__version__}")
`);

      ready = true;
      onProgress?.('Ready');
      return true;
    } catch (err) {
      console.error('[pyodideParser] Init failed:', err);
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
  const manifestRes = await fetch('/pylib/manifest.json');
  if (!manifestRes.ok) {
    throw new Error('Could not fetch /pylib/manifest.json — run prebuild first');
  }
  const manifest = await manifestRes.json();

  // Find site-packages path
  const sitePackages = pyodide.runPython('import site; site.getsitepackages()[0]');
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
    const parts = relPath.split('/');
    let dir = sitePackages;
    for (let i = 0; i < parts.length - 1; i++) {
      dir += '/' + parts[i];
      try {
        pyodide.FS.mkdir(dir);
      } catch {
        /* exists */
      }
    }

    const fullPath = dir + '/' + parts[parts.length - 1];
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
    pyodide.globals.set('_kir_input', kirText);

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
        "dataInputs": [{"name": p.port, "type": p.type, **({"default": p.default} if p.default is not None else {})} for p in n.data_inputs],
        "dataOutputs": [{"name": p.port, "type": p.type} for p in n.data_outputs],
        "ctrlInputs": n.ctrl_inputs,
        "ctrlOutputs": n.ctrl_outputs,
        **({"properties": n.properties} if n.properties else {}),
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
    console.error('[pyodideParser] Parse error:', err);
    return null;
  }
}

export function isPyodideReady() {
  return ready;
}

/**
 * Compile a .kirgraph JSON object to L2 KIR text using the Python
 * KirGraphCompiler pipeline inside Pyodide.
 *
 * @param {string} kirgraphJson - JSON.stringify()'d kirgraph object
 * @returns {Promise<string|null>} L2 KIR text, or null if Pyodide is not ready
 */
export async function compileGraphToKir(kirgraphJson) {
  if (!ready) {
    const ok = await initPyodide();
    if (!ok) return null;
  }

  try {
    pyodide.globals.set('_kirgraph_json_str', kirgraphJson);

    const kirText = await pyodide.runPythonAsync(`
import json
from kohakunode.kirgraph.schema import KirGraph
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.serializer.writer import Writer

kg_dict = json.loads(_kirgraph_json_str)
graph = KirGraph.from_dict(kg_dict)
program = KirGraphCompiler().compile(graph)
Writer().write(program)
`);

    return kirText;
  } catch (err) {
    console.error('[pyodideParser] compileGraphToKir error:', err);
    return null;
  }
}

/**
 * Parse KIR text using Python and return a plain-JS AST object.
 * Returns null on failure.
 *
 * The returned object mirrors the Python dataclass structure:
 *   { type: 'Program', body: [...statements], mode: string|null }
 *
 * Each statement has a `type` field matching the Python class name
 * (FuncCall, Assignment, Branch, Switch, Parallel, Jump, Namespace,
 *  DataflowBlock, SubgraphDef, ModeDecl) plus type-specific fields.
 *
 * @param {string} kirText
 * @returns {Promise<object|null>}
 */
export async function parseKirToAst(kirText) {
  if (!ready) {
    const ok = await initPyodide();
    if (!ok) return null;
  }

  try {
    pyodide.globals.set('_kir_ast_input', kirText);

    const resultJson = await pyodide.runPythonAsync(`
import json
from kohakunode import parse

def _serialize_expr(expr):
    if expr is None:
        return None
    t = type(expr).__name__
    if t == 'Identifier':
        return {'type': 'Identifier', 'name': expr.name}
    if t == 'Literal':
        return {'type': 'Literal', 'value': expr.value, 'literal_type': expr.literal_type}
    if t == 'KeywordArg':
        return {'type': 'KeywordArg', 'name': expr.name, 'value': _serialize_expr(expr.value)}
    if t == 'LabelRef':
        return {'type': 'LabelRef', 'name': expr.name}
    if t == 'Wildcard':
        return {'type': 'Wildcard'}
    return {'type': t, 'repr': repr(expr)}

def _serialize_output(out):
    if out is None:
        return '_'
    if isinstance(out, str):
        return out
    t = type(out).__name__
    if t == 'Wildcard':
        return '_'
    return str(out)

def _serialize_stmt(stmt):
    t = type(stmt).__name__
    base = {'type': t, 'line': stmt.line}
    if t == 'FuncCall':
        base['func_name'] = stmt.func_name
        base['inputs'] = [_serialize_expr(i) for i in stmt.inputs]
        base['outputs'] = [_serialize_output(o) for o in stmt.outputs]
    elif t == 'Assignment':
        base['target'] = stmt.target
        base['value'] = _serialize_expr(stmt.value)
    elif t == 'Branch':
        base['condition'] = _serialize_expr(stmt.condition)
        base['true_label'] = stmt.true_label
        base['false_label'] = stmt.false_label
    elif t == 'Switch':
        base['value'] = _serialize_expr(stmt.value)
        base['cases'] = [[_serialize_expr(e), lbl] for e, lbl in stmt.cases]
        base['default_label'] = stmt.default_label
    elif t == 'Jump':
        base['target'] = stmt.target
    elif t == 'Parallel':
        base['labels'] = list(stmt.labels)
    elif t == 'Namespace':
        base['name'] = stmt.name
        base['body'] = [_serialize_stmt(s) for s in stmt.body]
    elif t == 'DataflowBlock':
        base['body'] = [_serialize_stmt(s) for s in stmt.body]
    elif t == 'SubgraphDef':
        base['name'] = stmt.name
        base['params'] = [{'name': p.name, 'default': _serialize_expr(p.default)} for p in stmt.params]
        base['outputs'] = list(stmt.outputs)
        base['body'] = [_serialize_stmt(s) for s in stmt.body]
    elif t == 'ModeDecl':
        base['mode'] = stmt.mode
    return base

_prog = parse(_kir_ast_input)
_ast_result = {
    'type': 'Program',
    'mode': _prog.mode,
    'body': [_serialize_stmt(s) for s in _prog.body],
}
json.dumps(_ast_result)
`);

    return JSON.parse(resultJson);
  } catch (err) {
    console.error('[pyodideParser] parseKirToAst error:', err);
    return null;
  }
}
