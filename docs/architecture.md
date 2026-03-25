# KohakuNodeIR — System Architecture

**Version**: 0.1.0-draft

## 1. Overview

KohakuNodeIR is a portable IR language and toolchain for node-based visual programming. The core is a Python library — any UI that emits `.kir` can run on any conforming backend.

**Core packages:**

- **`kohakunode`** — IR engine: parser, compiler, executor, layout system
- **`kohakunode_viewer`** — static browser viewer (Vue 3 + Pyodide, no server needed)
- **`kohakunode_utils`** — ComfyUI workflow import/export

```
  ┌──────────────────────────────────────────────────────────────┐
  │              kohakunode — Python IR engine                   │
  │                                                              │
  │  Parser  →  AST  →  Validator  →  DataflowCompiler          │
  │                                         │                    │
  │  KirGraphCompiler  ←→  KirGraphDecompiler                   │
  │  (L1→L2)                (L2→L1)         │                    │
  │                                    Interpreter               │
  │                                         │                    │
  │                                    Registry (functions)      │
  │                                                              │
  │  Layout: auto_layout / score / optimizer / ascii_view        │
  └──────────────────────────────────────────────────────────────┘
```

The `kir-editor/` directory contains an **example** full-stack application (Vue 3 node editor + FastAPI execution server) demonstrating how to build on top of the core. It is not part of the core toolchain.

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
  layout/
    ascii_view.py      kir_to_graph() — extract KirGraph from .kir AST
    auto_layout.py     auto_layout() — Fischer-style BFS placement
    score.py           score_layout() — wire-bending quality metric
    optimizer.py       optimize_layout() — local-search improvement
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

## 4. Control Flow and Dataflow Coexistence

A key design feature is that control flow and dataflow are not competing paradigms — they compose inside the same file.

### 4.1 How They Coexist

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

### 4.2 `@dataflow:` Block Semantics

- The block is a scope containing statements whose execution order is determined by data dependencies (topological sort).
- The `DataflowCompiler` expands each block: topologically sorts its statements and inlines them into the parent body.
- After compilation, no `@dataflow:` wrappers remain in the L3 output.
- Blocks can appear at the top level, inside namespaces (loop bodies, branches), and inside `@def` bodies.
- A statement `(total, x)add(total)` where the output re-uses an input name is not a cycle — the output variable is excluded from its own dependency inputs.

#### Control-flow edge treatment of `@dataflow:` blocks

Nodes inside a `@dataflow:` block have **no internal control edges** — the ordering within the block is purely data-driven. However, the block as a whole participates in the surrounding control chain via **boundary control edges**:

- **Entry boundary**: a ctrl edge from the last control-connected node before the block to the first node inside the block.
- **Exit boundary**: the last node inside the block becomes the `last_ctrl` for the enclosing scope, so the next control-connected node after the block receives a ctrl edge from it.

This means that in a `KirGraph` extracted from `.kir` source (e.g., by `kir_to_graph` in `layout/ascii_view.py`), a `@dataflow:` block appears as a chain segment within the overall control flow, even though the ordering of statements inside the block is determined by data dependencies rather than ctrl wires. The boundary edges allow layout algorithms and graph viewers to position the block correctly relative to the surrounding control flow.

### 4.3 Dependent Data Nodes

Nodes that have no control edges but whose data inputs come from control-connected nodes are called "dependent data nodes". The `KirGraphCompiler` places them in `@dataflow:` blocks immediately after the control node that produces their inputs, inside the same scope.

### 4.4 Merge Node Synthesis

When multiple control edges converge on the same target node — for example at a loop entry point where the initial forward flow and the back-edge both arrive — a **merge node** is automatically synthesized. The merge node collects all incoming ctrl edges and emits a single ctrl output to the target. This synthesis happens:

- During L1 → L2 compilation (`KirGraphCompiler`): a merge node in the `.kirgraph` is compiled to `()jump(\`ns_{id}\`)` + `ns_{id}:` namespace.
- During graph extraction from `.kir` source (`kir_to_graph`): after walking all statements, any node with two or more incoming ctrl edges gets a synthetic merge node inserted with N `in_i` ports, and all original edges are rewired through it.

---

## 5. Layout System

Located at `src/kohakunode/layout/`. All components operate on `KirGraph` objects and require no running UI or server.

### 5.1 Graph Extraction from KIR (`ascii_view.py`)

`kir_to_graph(source: str) -> KirGraph` parses a `.kir` source string and builds a `KirGraph` by walking the AST directly. Unlike the decompiler, it does not require the `{node_id}_{port}` variable naming convention — it tracks all variable definitions and usages to wire data edges.

Key behaviors:

- **Control flow**: `FuncCall` nodes are connected by ctrl edges in statement order. `Branch`/`Switch`/`Parallel` nodes walk their child namespaces and pass the correct port name (`"true"`, `"false"`, etc.) to the recursive walk.
- **`@dataflow:` boundary edges**: The block is walked with `in_dataflow=True` (no internal ctrl edges), but entry and exit boundary ctrl edges connect it to the surrounding control chain (see Section 4.2).
- **`Jump` statements**: Recorded as deferred wires; after the full walk, each jump is resolved to the first node inside the target namespace.
- **Merge node synthesis**: After all wires are resolved, any node with 2+ incoming ctrl edges gets a synthetic merge node (see Section 6.4).
- **Literal defaults**: For `FuncCall` inputs that are `Literal` values (not variable references), the value is stored as `KGPort.default` rather than creating a data edge.
- **`@meta` annotations**: If the statement has `@meta node_id=...`, that id is used directly rather than generating a new one; `@meta pos=(x, y)` is stored in the node's `meta` field.

The module also exposes `print_graph()`, `print_ascii_layout()`, and `print_edge_analysis()` for terminal inspection, and a `__main__` entry point:

```bash
python -m kohakunode.layout.ascii_view path/to/file.kir
python -m kohakunode.layout.ascii_view path/to/file.kirgraph
```

### 5.2 Automatic Layout (`auto_layout.py`)

`auto_layout(graph: KirGraph) -> KirGraph` assigns pixel positions and sizes to all nodes that lack them (nodes with `pos=[0,0]` or no `pos` key). Already-positioned nodes are left untouched.

Algorithm (Fischer-style):

1. **Ctrl root detection**: find nodes with ctrl outputs but no forward-incoming ctrl edges (cycles/back-edges are detected by comparing node rank order).
2. **BFS ctrl chain** downward from root at column 0: each step increments the row counter. Back-edges are skipped. Remaining ctrl nodes unreachable from the initial BFS (e.g., after a `@dataflow:` gap) are handled by a second pass.
3. **Data sources left**: BFS backward through data edges, placing each source one column to the left of its consumer at the same row.
4. **Data consumers right**: BFS forward through data edges, placing each consumer one column to the right of its sources.
5. **Unconnected nodes**: appended below the placed graph.
6. **Pixel conversion**: column widths are derived from estimated node sizes; rows use a fixed `MIN_HEIGHT + V_SPACING` step.

Node sizes are estimated from port counts (`estimate_node_size()`); merge nodes use a compact height formula.

### 5.3 Layout Scoring (`score.py`)

`score_layout(graph: KirGraph) -> LayoutScore` measures layout quality. Lower is better; 0 is perfect.

Scoring rules:

| Edge type | Ideal direction | Backward penalty |
|---|---|---|
| Control | Same column (col_diff=0), 1 row down | 3× on both axes |
| Data | Same row (row_diff=0), 1 column right | 3× on col, 2× on row |

Additional penalties:
- **Edge crossings**: counted per adjacent column-pair using linear row interpolation for multi-column spans. 2.0 per crossing.
- **Node overlaps**: 10.0 per pair of nodes sharing the same grid cell.

`score_edge()` and `_count_crossings()` are exposed for use by the optimizer.

### 5.4 Layout Optimizer (`optimizer.py`)

`optimize_layout(graph: KirGraph, max_iterations=100) -> KirGraph` starts from the `auto_layout` result and applies greedy local search:

- **Strategy A** — swap two nodes within the same column (exchange their rows).
- **Strategy B** — move a node one column left or right.
- **Strategy C** — move a node one row up or down.

Each candidate move is accepted immediately if it strictly reduces the total score. The loop terminates when no strategy produces an improvement or `max_iterations` is exhausted.

---

## 6. KIR Viewer (`src/kohakunode_viewer/`)

A static Vue 3 SPA that renders `.kir`, `.kirgraph`, and ComfyUI workflow JSON in the browser with no server required. Dev server runs on port 5175.

### 6.1 Input formats

| Format | Detection | Parser |
|---|---|---|
| `.kirgraph` | File extension or `version`+`nodes`+`edges` JSON shape | `kirgraphLoader.js` |
| `.kir` | File extension or non-JSON content | Pyodide (real Python) or `kirLiteParser.js` fallback |
| ComfyUI workflow | `nodes`+`links` JSON shape | `comfyLoader.js` |
| ComfyUI API | `class_type` values in JSON | `comfyLoader.js` |

### 6.2 Pyodide KIR parser

For `.kir` input, the viewer loads [Pyodide](https://pyodide.org/) v0.27.1 from CDN, installs `lark` via `micropip`, then mounts the `kohakunode` Python source from `/pylib/` (fetched from the static server using a file manifest at `/pylib/manifest.json`).

Once loaded, the real `kir_to_graph` + `auto_layout` pipeline runs in WASM. This gives exact parity with the Python engine for all `.kir` features including control flow, `@dataflow:` blocks, and `@meta` annotations.

**Prebuild step**: before building or serving the viewer, copy the `kohakunode` Python source tree to `public/pylib/kohakunode/` and generate `public/pylib/manifest.json`. Without this step, Pyodide cannot mount the package and the viewer falls back to the JS lite parser.

### 6.3 Self-contained HTML export (`html_export.py`)

```python
from kohakunode_viewer.html_export import generate_html
from kohakunode.kirgraph.schema import KirGraph

graph = KirGraph.from_file("my_graph.kirgraph")
html = generate_html(graph.to_json())
open("viewer.html", "w").write(html)
```

`generate_html(kirgraph_json: str) -> str` embeds the graph JSON inline and produces a fully self-contained HTML file — no external CDN, no Pyodide, no build step. It renders nodes as positioned `<div>` elements with SVG bezier-curve edges, and supports pan (drag), zoom (Ctrl+wheel or pinch), and scroll. The colour scheme matches the Vue viewer (Catppuccin Mocha palette).

---

## 7. ComfyUI Utilities (`src/kohakunode_utils/`)

Installable as a separate package (`kohakunode_utils`). Provides import and export between ComfyUI workflow JSON and KirGraph.

### 7.1 Import: ComfyUI → KirGraph

`comfyui_to_kirgraph(workflow: dict) -> KirGraph` handles both formats:

- **Workflow format** (LiteGraph JSON): `nodes`/`links` arrays. Slot indices are resolved to port names. Widget values fill unconnected input slot defaults; remaining widget values become extra `widget_N` input ports.
- **API format** (prompt JSON): `class_type` + `inputs` dicts. Connection references `[node_id, slot]` become data edges; scalar values become port defaults. Output ports are inferred from which slots other nodes reference.

Node IDs are prefixed with `comfy_` to ensure uniqueness. Original ComfyUI metadata (type casing, slot info, widget values, flags, colors) is preserved in each node's `meta` dict for lossless round-trips.

### 7.2 Export: KirGraph → ComfyUI

`kirgraph_to_comfyui(graph: KirGraph) -> dict` reconstructs the ComfyUI workflow from `meta` fields written during import. If a node was not originally imported from ComfyUI (no `comfyui_type` in meta), the KirGraph port info is used directly. Only data edges are converted to links; control edges have no ComfyUI equivalent.

### 7.3 Direct conversion

`comfyui_to_kir(workflow: dict) -> str` chains import → `KirGraphCompiler` → `Writer` to produce L2 KIR text directly from a ComfyUI workflow dict.

---

## 8. Round-Tripping (L1 ↔ L2)

The system can reconstruct a `.kirgraph` from a `.kir` L2 file, enabling save/load of visual graphs via the text IR.

### 8.1 Forward (L1 → L2)

`KirGraphCompiler` emits `@meta node_id="<id>" pos=(x, y)` before every statement. This records:
- Which graph node this statement corresponds to
- The visual position of that node in the canvas

### 8.2 Reverse (L2 → L1)

`KirGraphDecompiler` performs two passes:

1. **Node creation pass**: Walk all statements. For each statement with `@meta node_id=...`, create a `KGNode`. Type is inferred from statement kind: `Assignment` → value node, `FuncCall` → function node with type = `func_name`, `Branch` → branch node, etc. Port names are extracted from the statement's inputs/outputs.

2. **Edge creation pass**: Walk all statements again. For each input identifier that matches `{node_id}_{port}` of a known node, create a data edge. Control edges are reconstructed from the namespace/branch/switch/parallel topology.

Variable naming convention `{node_id}_{port_name}` (e.g., `add1_result`) is what makes decompilation reliable. The decompiler splits variable names on this pattern to recover the original node/port identities.

---

## Appendix: Example Full-Stack App (`kir-editor/`)

The `kir-editor/` directory contains an **example** application showing how to build a full node editor + execution server on top of the core `kohakunode` library. It is **not** part of the core toolchain.

- **`kir-editor/frontend/`** — Vue 3 node editor (Vite, Pinia, Element Plus, UnoCSS). Compiles graphs to `.kirgraph` JSON or KIR text, communicates with the backend via REST/WebSocket.
- **`kir-editor/backend/`** — FastAPI server. Exposes endpoints for executing KIR programs, compiling/decompiling between L1↔L2, and managing user-defined node types.

See `kir-editor/` source and `docs/api.md` for details.
