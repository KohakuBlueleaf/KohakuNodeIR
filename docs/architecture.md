# KohakuNodeIR — System Architecture

**Version**: 0.1.0-draft

## 1. Overview

KohakuNodeIR is a full-stack visual programming system. Users build programs by connecting nodes in a browser-based editor. The editor compiles the graph to KIR text, which a Python backend parses, validates, compiles, and executes.

```
  ┌──────────────────────────────────────────────────────────────┐
  │                    Browser (Vue 3 + Pinia)                   │
  │                                                              │
  │  Node Palette ──► Node Editor Canvas ──► IR Preview Panel   │
  │        │                │                        │           │
  │  NodeRegistry     graph store             graphToIr.js       │
  │  (fetched from    (nodes + edges)         kirgraph.js        │
  │   backend)                                                   │
  │                         │                                    │
  │              Save .kirgraph / Compile KIR                    │
  └─────────────────────────┼────────────────────────────────────┘
                            │ HTTP REST + WebSocket
  ┌─────────────────────────▼────────────────────────────────────┐
  │               Backend (FastAPI, Python 3.10+)                │
  │                                                              │
  │  POST /api/execute        WS /api/ws/execute                 │
  │  POST /api/nodes/register GET /api/nodes                     │
  │  DELETE /api/nodes/{type}                                    │
  │                                                              │
  │            ExecutionSession (captures output)                │
  │                      │                                       │
  │                   Executor                                   │
  │          parse → validate → compile → interpret              │
  └──────────────────────────────────────────────────────────────┘
                            │
  ┌─────────────────────────▼────────────────────────────────────┐
  │              kohakunode Python engine                        │
  │                                                              │
  │  Parser  →  AST  →  Validator  →  DataflowCompiler          │
  │                                         │                    │
  │                                    Interpreter               │
  │                                         │                    │
  │                                    Registry (functions)      │
  └──────────────────────────────────────────────────────────────┘
```

---

## 2. Three-Level IR Pipeline

The system uses three distinct IR levels. Every format is convertible to its neighbors.

```
  .kirgraph (JSON)          .kir L2 (text)           .kir L3 (text)
  ─────────────────         ─────────────────        ─────────────────
  nodes + edges             @dataflow: blocks        pure sequential
  no ordering               @meta annotations        no @dataflow:
  UI-native                 round-trippable          no @meta
                            human-readable           engine-ready

       │   L1→L2                    │   L2→L3
       │   KirGraphCompiler         │   DataflowCompiler
       │                            │   StripMetaPass (optional)
       ▼                            ▼

  L2 → L1: KirGraphDecompiler (reads @meta, reconstructs topology)
```

### 2.1 Level 1: `.kirgraph`

JSON format storing the raw graph topology. Produced by the frontend (via `kirgraph.js`) or generated programmatically. Contains no ordering — it is the UI's native save format.

Key structure:
- `nodes[]` — each node has `id`, `type`, `data_inputs`, `data_outputs`, `ctrl_inputs`, `ctrl_outputs`, `properties`, `meta`
- `edges[]` — each edge has `type` (`"data"` or `"control"`), `from {node, port}`, `to {node, port}`

### 2.2 Level 2: `.kir` with `@dataflow:` and `@meta`

Human-readable IR. Produced by `KirGraphCompiler` (Python) or `graphToIr.js` (JavaScript). Contains:
- `@meta node_id="..." pos=(x, y)` annotations before each statement — preserve graph layout for decompilation back to L1
- `@dataflow:` scoped blocks — statements whose order must be resolved by topological sort
- Control flow (namespaces, branch, switch, jump, parallel) — in execution order already

L2 is the **pivot format**: it can go forward to L3 (execution) or backward to L1 (UI reconstruction).

### 2.3 Level 3: `.kir` pure sequential

Produced by `DataflowCompiler` (expands `@dataflow:` blocks) and optionally `StripMetaPass` (removes `@meta`). This is what the interpreter actually runs. Contains only assignments, function calls, namespaces, and control-flow primitives — all in strict sequential order.

### 2.4 Compilation Example

Given a simple sum-of-squares loop graph (`examples/kirgraph_pipeline/source.kirgraph`):

**L1 fragment** (JSON):
```json
{
  "id": "val_limit", "type": "value",
  "properties": { "value": 3 },
  "ctrl_inputs": [], "ctrl_outputs": []
}
```

**L2 output** (compiled KIR with annotations):
```kir
@dataflow:
    @meta node_id="val_limit" pos=(100, 100)
    val_limit_value = 3
    @meta node_id="val_i" pos=(100, 380)
    val_i_value = 0
@meta node_id="merge_loop" pos=(340, -20)
()jump(`ns_merge_loop`)
ns_merge_loop:
    @meta node_id="inc_i" pos=(320, 100)
    (val_i_value, val_step_value)add(inc_i_result)
    @dataflow:
        @meta node_id="square" pos=(520, 100)
        (inc_i_result, inc_i_result)multiply(square_result)
```

**L3 output** (execution-ready, no `@dataflow:`, no `@meta`):
```kir
val_limit_value = 3
val_step_value = 1
val_total_value = 0
val_i_value = 0
()jump(`ns_merge_loop`)
ns_merge_loop:
    (val_i_value, val_step_value)add(inc_i_result)
    (inc_i_result, inc_i_result)multiply(square_result)
    (val_total_value, square_result)add(accum_result)
```

---

## 3. Python Engine

Located at `src/kohakunode/`. Installable as the `kohakunode` package.

### 3.1 Module Structure

```
src/kohakunode/
  __init__.py          Public API (all exports)
  errors.py            Exception hierarchy
  ast/
    nodes.py           All AST node dataclasses
    visitor.py         Visitor base class
  parser/
    parser.py          parse() / parse_file() — entry points
    transformer.py     Lark grammar transformer → AST
  analyzer/
    validator.py       Semantic validation (validate / validate_or_raise)
    variables.py       Variable definition/use tracking
    scope.py           Namespace scope analysis
    errors.py          Analysis-specific errors
  compiler/
    dataflow.py        DataflowCompiler — expand @dataflow: blocks (L2→L3)
    strip_meta.py      StripMetaPass — remove @meta annotations
    passes.py          IRPass base class, DependencyGraphBuilder, topological_sort
  engine/
    executor.py        Executor, run(), run_file() — main entry points
    interpreter.py     Interpreter — walks AST and executes statements
    context.py         VariableStore — flat variable scope
    registry.py        Registry, FunctionSpec — function lookup table
    builtins.py        Built-in control-flow utilities
  kirgraph/
    schema.py          KirGraph, KGNode, KGEdge, KGPort dataclasses
    compiler.py        KirGraphCompiler — L1→L2 (KirGraph → Program AST)
    decompiler.py      KirGraphDecompiler — L2→L1 (Program AST → KirGraph)
  serializer/
    reader.py          read() / read_string() — parse + deserialize
    writer.py          Writer — AST → KIR text
```

### 3.2 Execution Pipeline

```
source string / file
        │
        ▼
    parse()  ──► Program AST
        │
        ▼
    validate_or_raise()  ──► ValidationResult (errors, warnings)
        │
        ▼
    DataflowCompiler.transform()
        │  - @mode dataflow: toposort all statements
        │  - @dataflow: blocks: toposort each block, inline into parent
        │  - Namespaces / SubgraphDefs: recurse into body
        ▼
    Program AST (no @dataflow: blocks remain)
        │
        ▼
    Interpreter.run()
        │  - Assignment: evaluate RHS, bind to variable
        │  - FuncCall: look up in Registry, call, bind outputs
        │  - Branch: evaluate condition, goto true/false namespace
        │  - Switch: match value, goto matching namespace
        │  - Jump: goto target namespace (enables loops)
        │  - Parallel: execute all named namespaces (order unspecified)
        │  - Namespace: skip during sequential walk; entered only via above
        ▼
    VariableStore (final state)
```

### 3.3 Registry

The `Registry` maps function names (strings) to `FunctionSpec` objects. A `FunctionSpec` holds the callable, its input parameter names (introspected from the signature), its declared output names, and default values.

```python
from kohakunode import Registry, Executor

registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])

executor = Executor(registry=registry)
store = executor.execute_source("(3, 4)add(sum)")
print(store.get("sum"))  # 7
```

The decorator form:
```python
@registry.register_decorator(output_names=["result"])
def multiply(a, b):
    return a * b
```

### 3.4 Variable Store

`VariableStore` is a flat dictionary — all variables live in one scope regardless of nesting depth. Variables assigned inside a namespace are visible everywhere after the assignment. There is no block scoping.

```python
store.get("x")           # retrieve a variable
store.set("x", 42)       # set a variable
store.snapshot()         # dict of all current variables
```

### 3.5 Dataflow Compiler

`DataflowCompiler` handles two forms:

1. **`@mode dataflow`** (whole-file): topologically sorts all statements. Raises `KirCompilationError` if any control-flow construct is present.
2. **`@dataflow:` blocks** (scoped): each block is sorted independently and its statements are inlined into the parent body. The `@dataflow:` wrapper is removed. This works at any nesting level — inside namespaces, inside `@def` bodies, etc.

Topological sort uses `DependencyGraphBuilder` which maps each statement's output variables as provided nodes and its input variable references as dependency edges.

---

## 4. Frontend

Located at `app/frontend/`. Vue 3 SPA built with Vite.

### 4.1 Technology Stack

| Concern | Library |
|---------|---------|
| UI framework | Vue 3 (Composition API) |
| State management | Pinia |
| Component library | Element Plus |
| CSS utility | UnoCSS |
| Build tool | Vite 6 |
| HTTP client | Axios |
| Auto-imports | unplugin-auto-import, unplugin-vue-components |

Dev server: port `5174`. Vite proxies `/api/*` to the backend at `http://localhost:48888`.

### 4.2 Source Layout

```
app/frontend/src/
  main.js                  App bootstrap
  App.vue                  Root component
  compiler/
    graphToIr.js           Graph → KIR text (control-flow + dataflow modes)
    kirgraph.js            Graph → .kirgraph JSON / .kirgraph → Graph
  components/
    editor/
      NodeEditor.vue       Main editor shell (toolbar, panels, canvas)
      EditorCanvas.vue     SVG/HTML canvas, pan/zoom, event routing
      SelectionBox.vue     Rubber-band selection rectangle
    nodes/
      NodeRenderer.vue     Picks the right node component by type
      BaseNode.vue         Common node chrome (header, port rows, resize)
      FunctionNode.vue     Generic function call node
      BranchNode.vue       Branch (2 ctrl outputs)
      SwitchNode.vue       Switch (N ctrl outputs)
      MergeNode.vue        Merge / loop-entry node
      ParallelNode.vue     Parallel node
      ValueNode.vue        Literal value node (inline editor)
    panels/
      NodePalette.vue      Left panel: node type browser + drag-to-create
      PropertyPanel.vue    Right panel: selected node property editor
      NodeDefEditor.vue    Dialog: create / edit user-defined node code
      IrPreview.vue        Bottom panel: live KIR text preview
    ports/
      ControlPort.vue      Control port dot (top/bottom edge)
      DataPort.vue         Data port dot (left/right edge)
    wire/
      WireLayer.vue        SVG layer rendering all committed wires
      DraftWire.vue        SVG path for in-progress wire draw
  stores/
    graph.js               useGraphStore — nodes Map, connections Map
    editor.js              useEditorStore — pan/zoom, selection, draft wire, mode
    history.js             useHistoryStore — undo/redo snapshots
    nodeRegistry.js        useNodeRegistryStore — fetched node type catalog
  composables/
    useDrag.js             Node drag behavior
    useWireDraw.js         Wire draw behavior
    usePanZoom.js          Canvas pan + zoom
    useSelection.js        Box-select behavior
    useResize.js           Node resize handles
    useKeyboard.js         Keyboard shortcuts (Delete, Ctrl+Z, etc.)
  utils/
    bezier.js              Cubic Bezier wire path math
    grid.js                Grid snap helpers
  styles/
    global.css             Base styles, CSS custom properties
```

### 4.3 State Management (Pinia)

**`useGraphStore`** is the authoritative graph model:
- `nodes: Map<id, NodeData>` — reactive Map of all nodes
- `connections: Map<id, ConnectionData>` — reactive Map of all edges
- `addNode / removeNode / updateNodePosition / updateNodeSize` — mutations
- `addConnection / removeConnection` — edge mutations with validity check
- `getPortPosition(nodeId, portId)` — computes canvas-space port coordinates
- `serialize() / deserialize(snapshot)` — used by history store for undo/redo

**`useEditorStore`** holds transient UI state:
- `panX / panY / zoom` — canvas viewport transform
- `selectedNodeIds / selectedConnectionIds` — current selection
- `draftWire` — in-progress wire being drawn
- `mode` — `'controlflow'` or `'dataflow'` (affects IR compilation)
- `showCtrlPorts` — toggle control port visibility

### 4.4 Graph Compilers (JavaScript)

Two compilation paths exist in the frontend:

**Direct path** (`graphToIr.js`): Converts the in-memory graph store directly to KIR text. Handles both `controlflow` mode (walk control chains, emit namespaces) and `dataflow` mode (emit `@mode dataflow` header, emit all nodes unordered). This is used for the live IR preview and direct execution.

**KirGraph path** (`kirgraph.js`): Converts the graph store to a `.kirgraph` JSON object, which can then be sent to the Python backend's `KirGraphCompiler` for an authoritative L1→L2 compilation. Also handles the reverse: loading a `.kirgraph` file reconstructs the graph store.

### 4.5 Node Layout Model

Each node has:
- `dataPorts.inputs` — left edge, one row per port (fixed `DATA_ROW_H = 28px` per row)
- `dataPorts.outputs` — right edge, same row heights
- `controlPorts.inputs` — top edge, evenly spaced horizontally
- `controlPorts.outputs` — bottom edge, evenly spaced horizontally

Port positions are computed by `getPortPosition()` in `useGraphStore` and used by `WireLayer` to route wires.

---

## 5. Backend

Located at `app/backend/`. FastAPI application.

### 5.1 Files

```
app/backend/
  main.py          FastAPI app, all routes, WebSocket handler
  builtin_nodes.py Register standard library node types
  execution.py     ExecutionSession — runs KIR, captures output
  node_store.py    NodeStore — persist user node definitions to disk
  node_defs/       Auto-created directory; one JSON file per user node
```

### 5.2 Startup Sequence

1. Create global `Registry` and `NodeStore`
2. `register_builtins(registry)` — populate math, comparison, string, file, convert nodes
3. `node_store.register_all(registry)` — load saved user node definitions from `node_defs/*.json` and re-register them (uses `exec()` to compile the `node_func` Python code)
4. FastAPI app starts, CORS middleware allows all origins

### 5.3 Request Flow: REST Execute

```
POST /api/execute  {kir_source: "..."}
        │
        ▼
ExecutionSession(registry)
  ├── Override print/display to capture output into self.outputs list
  └── Executor(registry, validate=True).execute_source(kir_source)
        ├── parse(kir_source) → Program AST
        ├── validate_or_raise(program) → raises on errors
        ├── DataflowCompiler().transform(program) → sequential Program
        └── Interpreter(registry).run(program) → VariableStore
        │
        ▼
{"success": true, "variables": {...}, "output": [{type, value}, ...]}
```

### 5.4 Request Flow: WebSocket Execute

```
WS /api/ws/execute
  Client sends: {"type": "execute", "kir_source": "..."}
  Server sends (in order):
    {"type": "started"}
    {"type": "output", "value": "..."}   (one per captured print/display)
    {"type": "variable", "name": "...", "value": ...}  (one per variable)
    {"type": "completed", "variables": {...}}
  On error:
    {"type": "error", "message": "..."}
```

Execution runs in a thread pool (`loop.run_in_executor`) to avoid blocking the event loop.

### 5.5 User-Defined Node Code

User nodes are Python functions named `node_func`. They are stored as JSON in `node_defs/{type}.json` with a `code` field. On registration, the code is `exec()`-compiled and the resulting `node_func` callable is registered in the `Registry`.

```json
{
  "name": "My Squarer",
  "type": "my_squarer",
  "inputs": [{ "name": "value", "type": "float" }],
  "outputs": [{ "name": "result", "type": "float" }],
  "code": "def node_func(value):\n    return value * value"
}
```

---

## 6. Control Flow and Dataflow Coexistence

A key design feature is that control flow and dataflow are not competing paradigms — they compose inside the same file.

### 6.1 How They Coexist

Control-connected nodes are emitted in control-wire order by `KirGraphCompiler`. Nodes with no control wires are wrapped in `@dataflow:` blocks placed at the point where their data dependencies are satisfied.

This means a single `.kir` file can contain:

```kir
# Pure dataflow initialization (value nodes, no control wires)
@dataflow:
    val_limit_value = 3
    val_i_value = 0

# Pure control flow (loop)
()jump(`ns_loop`)
ns_loop:
    (val_i_value, 1)add(inc_i_result)

    # Dataflow block inside the loop body (re-executes each iteration)
    @dataflow:
        (inc_i_result, inc_i_result)multiply(square_result)
        (total, square_result)add(total)

    (inc_i_result, val_limit_value)less_than(keep_going)
    (keep_going)branch(`cont`, `done`)
    cont:
        ()jump(`ns_loop`)
    done:

# Dataflow post-processing (sees final variable values from loop)
@dataflow:
    (total)to_string(total_str)
    ("Result: ", total_str)concat(message)
    (message)print()
```

### 6.2 `@dataflow:` Block Semantics

- The block is a scope containing statements whose execution order is determined by data dependencies (topological sort).
- The `DataflowCompiler` expands each block: topologically sorts its statements and inlines them into the parent body.
- After compilation, no `@dataflow:` wrappers remain in the L3 output.
- Blocks can appear at the top level, inside namespaces (loop bodies, branches), and inside `@def` bodies.
- A statement `(total, x)add(total)` where the output re-uses an input name is not a cycle — the output variable is excluded from its own dependency inputs.

### 6.3 Dependent Data Nodes

Nodes that have no control edges but whose data inputs come from control-connected nodes are called "dependent data nodes". The `KirGraphCompiler` places them in `@dataflow:` blocks immediately after the control node that produces their inputs, inside the same scope.

---

## 7. Round-Tripping (L1 ↔ L2)

The system can reconstruct a `.kirgraph` from a `.kir` L2 file, enabling save/load of visual graphs via the text IR.

### 7.1 Forward (L1 → L2)

`KirGraphCompiler` emits `@meta node_id="<id>" pos=(x, y)` before every statement. This records:
- Which graph node this statement corresponds to
- The visual position of that node in the canvas

### 7.2 Reverse (L2 → L1)

`KirGraphDecompiler` performs two passes:

1. **Node creation pass**: Walk all statements. For each statement with `@meta node_id=...`, create a `KGNode`. Type is inferred from statement kind: `Assignment` → value node, `FuncCall` → function node with type = `func_name`, `Branch` → branch node, etc. Port names are extracted from the statement's inputs/outputs.

2. **Edge creation pass**: Walk all statements again. For each input identifier that matches `{node_id}_{port}` of a known node, create a data edge. Control edges are reconstructed from the namespace/branch/switch/parallel topology.

Variable naming convention `{node_id}_{port_name}` (e.g., `add1_result`) is what makes decompilation reliable. The decompiler splits variable names on this pattern to recover the original node/port identities.
