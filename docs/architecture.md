# KohakuNodeIR -- System Architecture

## 1. Overview

KohakuNodeIR is a visual node-based programming system built around the KIR intermediate representation. The system has three main components:

- **`kohakunode`** (Python) -- IR engine: Lark-based parser, compiler, executor, layout system
- **`kohakunode-rs`** (Rust) -- Core reimplementation: parser, compiler, layout, serializer. Compiles as a PyO3 native module or as WASM via wasm-bindgen
- **KIR Editor** (`kir-editor/`) -- Full-stack visual editor: Vue 3 node editor + FastAPI backend

```
  +--------------------------------------------------------------+
  |              kohakunode -- Python IR engine                   |
  |                                                              |
  |  Parser  ->  AST  ->  Validator  ->  DataflowCompiler        |
  |                                         |                    |
  |  KirGraphCompiler  <->  KirGraphDecompiler                   |
  |  (L1->L2)                (L2->L1)       |                    |
  |                                    Interpreter               |
  |                                         |                    |
  |                                    Registry (functions)      |
  |                                                              |
  |  Layout: auto_layout / score / optimizer / ascii_view        |
  +--------------------------------------------------------------+

  +--------------------------------------------------------------+
  |             kohakunode-rs -- Rust core                        |
  |                                                              |
  |  pest parser -> AST -> DataflowCompiler -> StripMetaPass     |
  |  KirGraphCompiler / Decompiler                               |
  |  Layout: auto_layout / score / optimizer                     |
  |  Serializer: AST -> KIR text                                 |
  |                                                              |
  |  Targets:  PyO3 native module  |  WASM (wasm-bindgen)       |
  +--------------------------------------------------------------+

  +--------------------------------------------------------------+
  |              KIR Editor (kir-editor/)                         |
  |                                                              |
  |  Frontend: Vue 3 + Vite + Pinia + Element Plus + UnoCSS      |
  |    - Node editor canvas with drag/drop, wiring, zoom/pan     |
  |    - WASM module for live IR preview and syntax validation    |
  |    - Code node with embedded Monaco editor                   |
  |    - Custom node system with property schema widgets          |
  |    - Output panel with collapsible variables accordion       |
  |                                                              |
  |  Backend: FastAPI + WebSocket                                |
  |    - KIR execution engine                                    |
  |    - Node registration and persistence                       |
  |    - Graph compilation and decompilation endpoints            |
  +--------------------------------------------------------------+
```

---

## 2. Three-Level IR Pipeline

The system uses three distinct IR levels. Every format is convertible to its neighbors.

```
  .kirgraph (JSON)          .kir L2 (text)           .kir L3 (text)
  -----------------         -----------------        -----------------
  nodes + edges             @dataflow: blocks        pure sequential
  no ordering               @meta annotations        no @dataflow:
  UI-native                 round-trippable          no @meta
                            human-readable           engine-ready

       |   L1->L2                    |   L2->L3
       |   KirGraphCompiler          |   DataflowCompiler
       |                             |   StripMetaPass (optional)
       v                             v

  L2 -> L1: KirGraphDecompiler (reads @meta, reconstructs topology)
```

### 2.1 Level 1: `.kirgraph`

JSON format storing the raw graph topology. Produced by the frontend (via `kirgraph.js`) or generated programmatically. Contains no ordering -- it is the UI's native save format.

Key structure:
- `nodes[]` -- each node has `id`, `type`, `data_inputs`, `data_outputs`, `ctrl_inputs`, `ctrl_outputs`, `properties`, `meta`
- `edges[]` -- each edge has `type` (`"data"` or `"control"`), `from {node, port}`, `to {node, port}`

### 2.2 Level 2: `.kir` with `@dataflow:` and `@meta`

Human-readable IR. Produced by `KirGraphCompiler` (in Python or Rust). Contains:
- `@meta node_id="..." pos=(x, y)` annotations before each statement -- preserve graph layout for decompilation back to L1
- `@dataflow:` scoped blocks -- statements whose order must be resolved by topological sort
- Control flow (namespaces, branch, switch, jump, parallel) -- in execution order already

L2 is the **pivot format**: it can go forward to L3 (execution) or backward to L1 (UI reconstruction).

### 2.3 Level 3: `.kir` pure sequential

Produced by `DataflowCompiler` (expands `@dataflow:` blocks) and optionally `StripMetaPass` (removes `@meta`). This is what the interpreter actually runs. Contains only assignments, function calls, namespaces, and control-flow primitives -- all in strict sequential order.

### 2.4 Compilation Example

Given a branching computation graph (`examples/kirgraph_pipeline/source.kirgraph`):
adds x=4 and y=7, checks if the sum is below a threshold (10), and either prints the
sum (if small) or computes and prints the product x*y (if large or equal).

**L1 fragment** (JSON):
```json
{
  "id": "val_x", "type": "value",
  "properties": { "value_type": "int", "value": 4 },
  "ctrl_inputs": [], "ctrl_outputs": []
}
```

**L2 output** (compiled KIR with annotations):
```kir
@dataflow:
    @meta node_id="val_x" pos=(100, 100) size=[160, 100]
    val_x_value = 4
    @meta node_id="val_y" pos=(100, 240) size=[160, 100]
    val_y_value = 7
    @meta node_id="val_threshold" pos=(100, 380) size=[160, 100]
    val_threshold_value = 10
@meta node_id="add_xy" pos=(320, 160) size=[180, 120]
(val_x_value, val_y_value)add(add_xy_result)
@meta node_id="check" pos=(540, 160) size=[200, 120]
(add_xy_result, val_threshold_value)less_than(check_result)
@meta node_id="branch" pos=(540, 320) size=[180, 120]
(check_result)branch(`branch_true`, `branch_false`)
branch_true:
    @meta node_id="msg_small" pos=(760, 200) size=[160, 100]
    (add_xy_result)print()
branch_false:
    @meta node_id="mul_xy" pos=(760, 400) size=[180, 120]
    (val_x_value, val_y_value)multiply(mul_xy_result)
    ...
```

**L3 output** (execution-ready, no `@dataflow:`, no `@meta`):
```kir
val_x_value = 4
val_threshold_value = 10
val_y_value = 7
(val_x_value, val_y_value)add(add_xy_result)
(add_xy_result, val_threshold_value)less_than(check_result)
(check_result)branch(`branch_true`, `branch_false`)
branch_true:
    (add_xy_result)print()
branch_false:
    (val_x_value, val_y_value)multiply(mul_xy_result)
    (mul_xy_result)to_string(to_str_result)
    ("x*y = ", to_str_result)concat(fmt_result)
    (fmt_result)print()
```

---

## 3. Rust Core (`src/kohakunode-rs/`)

The Rust crate `kohakunode-rs` reimplements the core pipeline in Rust for performance and cross-platform deployment.

### 3.1 Dual build targets

The crate supports two build targets via Cargo features:

- **`python` (default)** -- builds a PyO3 native extension module via maturin. This gives Python code access to fast Rust implementations of parsing, compilation, and layout.
- **`wasm`** -- builds a WASM module via `wasm-bindgen`. This is used by the KIR Editor frontend for in-browser parsing, compilation, and layout without any server round-trip.

The build script `scripts/build-wasm.sh` compiles to `wasm32-unknown-unknown` and runs `wasm-bindgen --target web` to produce JS glue in `kir-editor/frontend/src/wasm/`.

### 3.2 Module structure

```
src/kohakunode-rs/src/
  lib.rs               Crate root, feature-gated module includes
  ast/
    types.rs           AST node types (Program, Statement, Expr, etc.)
    mod.rs             Module re-exports
    pyo3.rs            PyO3 bindings for AST types
  parser/
    mod.rs             pest-based KIR parser
    indentation.rs     Indentation-sensitive preprocessing
    pyo3.rs            PyO3 bindings
  compiler/
    dataflow.rs        DataflowCompiler -- expand @dataflow: blocks
    strip_meta.rs      StripMetaPass -- remove @meta annotations
    mod.rs             Module re-exports
    pyo3.rs            PyO3 bindings
  analyzer/
    mod.rs             Semantic validation
    pyo3.rs            PyO3 bindings
  kirgraph/
    mod.rs             KirGraph schema, JSON serialization
    compiler.rs        KirGraphCompiler -- L1->L2
    decompiler.rs      KirGraphDecompiler -- L2->L1
    pyo3.rs            PyO3 bindings
  serializer/
    mod.rs             AST -> KIR text writer
    pyo3.rs            PyO3 bindings
  layout/
    auto_layout.rs     Fischer-style BFS layout
    score.rs           Wire-bending quality metric
    optimizer.rs       Local-search improvement
    mod.rs             kir_to_graph() extraction
    pyo3.rs            PyO3 bindings
  pyo3_module.rs       Top-level PyO3 module definition
  wasm_module.rs       wasm-bindgen exports (mirrors the PyO3 API)
```

### 3.3 WASM API

The WASM module (`wasm_module.rs`) exposes the following functions, all operating on JSON strings:

| Function | Input | Output | Purpose |
|---|---|---|---|
| `parse_kir(text)` | KIR source | Program AST JSON | Parse KIR to AST |
| `compile_dataflow(program_json)` | Program JSON | Program JSON | Expand `@dataflow:` blocks |
| `strip_meta(program_json)` | Program JSON | Program JSON | Remove `@meta` annotations |
| `compile_kirgraph(kirgraph_json)` | KirGraph JSON | Program JSON | L1 -> L2 compilation |
| `write_kir(program_json)` | Program JSON | KIR text | Serialize AST to KIR text |
| `kir_to_graph(source)` | KIR source | KirGraph JSON | Extract graph from `.kir` |
| `auto_layout(graph_json)` | KirGraph JSON | KirGraph JSON | Assign node positions |
| `score_layout(graph_json)` | KirGraph JSON | `f64` | Layout quality score |
| `optimize_layout(graph_json, n)` | KirGraph JSON + iterations | KirGraph JSON | Improve layout |
| `decompile(program_json)` | Program JSON | KirGraph JSON | L2 -> L1 decompilation |

The frontend loads the WASM module at startup (`wasmParser.js`). When ready, the IR Preview panel compiles graphs entirely in the browser; it falls back to a JS lite compiler while WASM is loading.

---

## 4. Python Engine (`src/kohakunode/`)

Located at `src/kohakunode/`. Installable as the `kohakunode` package.

### 4.1 Module structure

```
src/kohakunode/
  __init__.py          Public API (all exports)
  errors.py            Exception hierarchy
  ast/
    nodes.py           All AST node dataclasses
    visitor.py         Visitor base class
  parser/
    parser.py          parse() / parse_file() -- entry points
    transformer.py     Lark grammar transformer -> AST
  analyzer/
    validator.py       Semantic validation (validate / validate_or_raise)
    variables.py       Variable definition/use tracking
    scope.py           Namespace scope analysis
    errors.py          Analysis-specific errors
  compiler/
    dataflow.py        DataflowCompiler -- expand @dataflow: blocks (L2->L3)
    strip_meta.py      StripMetaPass -- remove @meta annotations
    passes.py          IRPass base class, DependencyGraphBuilder, topological_sort
  engine/
    executor.py        Executor, run(), run_file() -- main entry points
    interpreter.py     Interpreter -- walks AST and executes statements
    context.py         VariableStore -- flat variable scope
    registry.py        Registry, FunctionSpec -- function lookup table
    builtins.py        Built-in control-flow utilities
  kirgraph/
    schema.py          KirGraph, KGNode, KGEdge, KGPort dataclasses
    compiler.py        KirGraphCompiler -- L1->L2 (KirGraph -> Program AST)
    decompiler.py      KirGraphDecompiler -- L2->L1 (Program AST -> KirGraph)
  serializer/
    reader.py          read() / read_string() -- parse + deserialize
    writer.py          Writer -- AST -> KIR text
  layout/
    ascii_view.py      kir_to_graph() -- extract KirGraph from .kir AST
    auto_layout.py     auto_layout() -- Fischer-style BFS placement
    score.py           score_layout() -- wire-bending quality metric
    optimizer.py       optimize_layout() -- local-search improvement
  grammar/             Lark grammar file
```

### 4.2 Execution pipeline

```
source string / file
        |
        v
    parse()  --> Program AST
        |
        v
    validate_or_raise()  --> ValidationResult (errors, warnings)
        |
        v
    DataflowCompiler.transform()
        |  - @mode dataflow: toposort all statements
        |  - @dataflow: blocks: toposort each block, inline into parent
        |  - Namespaces / SubgraphDefs: recurse into body
        v
    Program AST (no @dataflow: blocks remain)
        |
        v
    Interpreter.run()
        |  - Assignment: evaluate RHS, bind to variable
        |  - FuncCall: look up in Registry, call, bind outputs
        |  - Branch: evaluate condition, goto true/false namespace
        |  - Switch: match value, goto matching namespace
        |  - Jump: goto target namespace (enables loops)
        |  - Parallel: execute all named namespaces (order unspecified)
        |  - Namespace: skip during sequential walk; entered only via above
        v
    VariableStore (final state)
```

### 4.3 Registry

The `Registry` maps function names to `FunctionSpec` objects. A `FunctionSpec` holds the callable, its input parameter names, output names, and default values.

```python
from kohakunode import Registry, Executor

registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])

executor = Executor(registry=registry)
store = executor.execute_source("(3, 4)add(sum)")
print(store.get("sum"))  # 7
```

### 4.4 Variable store

`VariableStore` is a flat dictionary -- all variables live in one scope regardless of nesting depth. Variables assigned inside a namespace are visible everywhere after the assignment.

### 4.5 Dataflow compiler

`DataflowCompiler` handles two forms:

1. **`@mode dataflow`** (whole-file): topologically sorts all statements. Raises `KirCompilationError` if any control-flow construct is present.
2. **`@dataflow:` blocks** (scoped): each block is sorted independently and its statements are inlined into the parent body. Works at any nesting level.

---

## 5. KIR Editor (`kir-editor/`)

The KIR Editor is the visual node editor frontend and execution backend.

### 5.1 Frontend architecture

Located at `kir-editor/frontend/`. Built with Vue 3, Vite, Pinia, Element Plus, and UnoCSS.

```
kir-editor/frontend/src/
  App.vue              Root layout
  main.js              App entry point
  api/                 Backend API client (REST + WebSocket)
  compiler/            JS graph-to-IR compiler (fallback), kirgraph builder
  components/
    blocks/            Canvas blocks (selection, pan, zoom)
    editor/            Canvas-level editor components
    nodes/             Node renderers (BaseNode, FunctionNode, ValueNode,
                       BranchNode, SwitchNode, MergeNode, ParallelNode,
                       CodeNode)
    panels/            Side panels (NodePalette, PropertyPanel,
                       NodeDefEditor, IrPreview)
    ports/             Port rendering and connection drawing
    wire/              Wire/connection components
  composables/         Vue composables (drag, zoom, connection, etc.)
  editor/              Monaco editor KIR language definition
  layout/              Frontend layout utilities
  parser/              WASM parser integration (wasmParser.js)
  stores/              Pinia stores (graph, editor, history, nodeRegistry)
  styles/              Global styles
  utils/               Persistence, helpers
  wasm/                WASM build output (kohakunode_rs.wasm + JS glue)
```

#### WASM integration

The WASM module (`parser/wasmParser.js`) initializes the Rust WASM module at startup. Once ready, it provides:

- **Live IR preview**: the IR Preview panel compiles the graph to KIR L2 and L3 entirely in the browser using the WASM `compile_kirgraph`, `compile_dataflow`, `strip_meta`, and `write_kir` functions
- **Syntax validation**: the Code node uses `parse_kir` from the WASM module to validate KIR syntax in real time within its embedded Monaco editor
- **Fallback**: while WASM is loading, a JS lite compiler produces L2 output; the UI shows a badge indicating which compiler is active (`WASM` or `JS`)

This replaces the previous Pyodide-based approach, which required loading a full Python runtime in the browser.

#### Code node

The Code node (`components/nodes/CodeNode.vue`) embeds a Monaco editor directly inside a graph node. It provides:

- KIR syntax highlighting via a registered Monaco language
- Real-time syntax validation using the WASM `parse_kir` function
- Bidirectional sync with the node's `properties.code` field
- Pointer event isolation so the editor can be used without triggering canvas drag

#### Custom node system

The Node Definition Editor (`components/panels/NodeDefEditor.vue`) allows creating new node types with:

- Custom input/output port definitions with data types
- **Property schemas** using typed widgets: `string`, `number`, `boolean`, `select` (dropdown with choices), and `slider` (range with min/max/step)
- Python code defining `node_func`
- Drag-to-reorder ports

Definitions are persisted to both localStorage (frontend) and the backend (`node_defs/` directory as JSON files). The `nodeRegistry` Pinia store syncs with the backend on startup.

#### Output panel

The IR Preview panel (`components/panels/IrPreview.vue`) provides:

- Tabbed view: KIR L2, KIR L3, KirGraph JSON
- Live syntax-highlighted IR output with line numbers
- Execute button with WebSocket streaming output
- **Collapsible Variables accordion**: after execution, the final variable store is displayed in a collapsible section with a chevron toggle

### 5.2 Backend architecture

Located at `kir-editor/backend/`. A FastAPI application.

```
kir-editor/backend/
  main.py              FastAPI app with all REST and WebSocket endpoints
  builtin_nodes.py     Built-in node type definitions and registration
  execution.py         ExecutionSession -- wraps the kohakunode executor
  node_store.py        Persistent storage for user-defined node definitions
  node_defs/           Directory for user-defined node JSON files
  requirements.txt     Backend Python dependencies
```

The backend provides:

- **REST endpoints**: node registration, listing, deletion; KIR execution; graph compilation/decompilation
- **WebSocket endpoints**: streaming execution with real-time output, variable, and completion events
- **Node persistence**: user-defined nodes are saved as JSON files in `node_defs/` and re-loaded on startup

See `docs/api.md` for the full endpoint reference.

---

## 6. Control Flow and Dataflow Coexistence

A key design feature is that control flow and dataflow compose inside the same file.

### 6.1 How they coexist

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

### 6.2 `@dataflow:` block semantics

- The block contains statements whose execution order is determined by data dependencies (topological sort).
- The `DataflowCompiler` expands each block: topologically sorts its statements and inlines them into the parent body.
- After compilation, no `@dataflow:` wrappers remain in the L3 output.
- Blocks can appear at the top level, inside namespaces (loop bodies, branches), and inside `@def` bodies.
- A statement `(total, x)add(total)` where the output re-uses an input name is not a cycle -- the output variable is excluded from its own dependency inputs.

#### Control-flow edge treatment of `@dataflow:` blocks

Nodes inside a `@dataflow:` block have no internal control edges -- the ordering within the block is purely data-driven. However, the block as a whole participates in the surrounding control chain via boundary control edges:

- **Entry boundary**: a ctrl edge from the last control-connected node before the block to the first node inside the block.
- **Exit boundary**: the last node inside the block becomes the `last_ctrl` for the enclosing scope, so the next control-connected node after the block receives a ctrl edge from it.

### 6.3 Merge node synthesis

When multiple control edges converge on the same target node -- for example at a loop entry point where the initial forward flow and the back-edge both arrive -- a merge node is automatically synthesized. This synthesis happens:

- During L1 -> L2 compilation (`KirGraphCompiler`): a merge node in the `.kirgraph` is compiled to `()jump(\`ns_{id}\`)` + `ns_{id}:` namespace.
- During graph extraction from `.kir` source (`kir_to_graph`): after walking all statements, any node with two or more incoming ctrl edges gets a synthetic merge node inserted.

---

## 7. ComfyUI Utilities (`src/kohakunode_utils/`)

Installable as a separate package. Provides import and export between ComfyUI workflow JSON and KirGraph.

### 7.1 Import: ComfyUI -> KirGraph

`comfyui_to_kirgraph(workflow: dict) -> KirGraph` handles both formats:

- **Workflow format** (LiteGraph JSON): `nodes`/`links` arrays. Widget values fill unconnected input slot defaults.
- **API format** (prompt JSON): `class_type` + `inputs` dicts. Connection references become data edges; scalar values become port defaults.

### 7.2 Export: KirGraph -> ComfyUI

`kirgraph_to_comfyui(graph: KirGraph) -> dict` reconstructs the ComfyUI workflow from `meta` fields written during import.

### 7.3 Direct conversion

`comfyui_to_kir(workflow: dict) -> str` chains import, compile, and write to produce L2 KIR text directly from a ComfyUI workflow dict.

---

## 8. Layout System

Located at `src/kohakunode/layout/` (Python) and `src/kohakunode-rs/src/layout/` (Rust). All components operate on `KirGraph` objects and require no running UI.

### 8.1 Graph extraction (`kir_to_graph`)

Parses a `.kir` source string and builds a `KirGraph` by walking the AST directly. Tracks all variable definitions and usages to wire data edges.

### 8.2 Automatic layout (`auto_layout`)

Fischer-style BFS: control chain runs vertically in column 0, data sources fan out left, data consumers fan out right. Cycle-aware (back-edges are skipped during placement).

### 8.3 Layout scoring (`score_layout`)

Wire-bending quality metric. Lower is better. Control edges are penalized for column deviation, data edges for row deviation, plus crossing and overlap penalties.

### 8.4 Layout optimizer (`optimize_layout`)

Local-search improvement over `auto_layout`: iteratively tries row swaps, column moves, and row shifts, accepting any improvement.

---

## 9. Round-Tripping (L1 <-> L2)

### 9.1 Forward (L1 -> L2)

`KirGraphCompiler` emits `@meta node_id="<id>" pos=(x, y)` before every statement, recording which graph node each statement corresponds to and its visual position.

### 9.2 Reverse (L2 -> L1)

`KirGraphDecompiler` performs two passes:

1. **Node creation pass**: Walk all statements. For each statement with `@meta node_id=...`, create a `KGNode`.
2. **Edge creation pass**: Walk all statements again. For each input identifier that matches `{node_id}_{port}` of a known node, create a data edge. Control edges are reconstructed from the namespace/branch/switch/parallel topology.

Variable naming convention `{node_id}_{port_name}` (e.g., `add1_result`) is what makes decompilation reliable.

---

## 10. Tree-sitter Grammar (`tree-sitter-kir/`)

A tree-sitter grammar for KIR syntax, used for editor integrations. The `tree-sitter-kir/vscode/` subdirectory contains a VS Code extension that provides syntax highlighting for `.kir` files using TextMate grammar scopes.
