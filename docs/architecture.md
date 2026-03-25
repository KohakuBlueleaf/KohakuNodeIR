# KohakuNodeIR -- System Architecture

## 1. Overview

KohakuNodeIR is a **language project**. The core product is **KIR** (Kohaku Node IR) -- a text-based intermediate representation designed to bridge visual node-graph UIs and backend execution engines. KIR supports both control-flow and data-flow visual programming styles in a single, human-readable format.

The system has four components, listed by importance:

1. **KIR the language** -- the IR specification itself. A three-level pipeline (graph topology, human-readable IR, execution-ready IR) with a namespace-based scope model that unifies control flow and dataflow in one file. See `spec.md` for the full language specification.

2. **kohakunode** (Python, `src/kohakunode/`) -- the reference implementation. Provides a Lark-based parser, AST, compiler passes, an execution engine with a pluggable function registry, a graph compiler/decompiler for round-tripping, and a layout system.

3. **kohakunode-rs** (Rust, `src/kohakunode-rs/`) -- a fast reimplementation of the core pipeline. Builds as a PyO3 native module (`import kohakunode_rs`) or as WASM via wasm-bindgen for browser use.

4. **KIR Editor** (`kir-editor/`) -- a reference application that demonstrates KIR in action. A Vue 3 node editor frontend with a FastAPI execution backend. It is a utility tool, not the core product.

---

## 2. The KIR Language Design

### 2.1 Why three levels of IR

KIR defines three representation levels, each convertible to its neighbors:

```
Level 1: .kirgraph (JSON)       Level 2: .kir (text)          Level 3: .kir (text)
----------------------------    -------------------------     ----------------------
Nodes + edges, positions        @dataflow: scopes, @meta      Pure sequential logic
No ordering, UI-native          Round-trippable to L1          No @dataflow:, no @meta
                                Human-readable                 Engine-ready
```

- **L1 to L2** (`KirGraphCompiler`): the graph compiler determines execution order, wraps unordered nodes in `@dataflow:` blocks, generates variable names, and emits `@meta` annotations for round-tripping.
- **L2 to L3** (`DataflowCompiler` + `StripMetaPass`): expands `@dataflow:` blocks via topological sort, optionally strips `@meta`. The result is flat sequential code the interpreter can run directly.
- **L2 to L1** (`KirGraphDecompiler`): reconstructs graph topology from `@meta` annotations and `{node_id}_{port}` variable naming conventions.

Level 2 is the **pivot format** -- it can go forward to execution (L3) or backward to a visual editor (L1).

### 2.2 Control flow and dataflow coexistence

A key design decision: control flow and dataflow compose inside the same `.kir` file rather than being separate modes.

- **Control-connected nodes** are emitted in control-wire order by the graph compiler. They use the four built-in utilities: `branch`, `switch`, `jump`, `parallel`.
- **Data-only nodes** (no control wires) are wrapped in `@dataflow:` blocks placed at the point where their data dependencies are satisfied. The dataflow compiler sorts them by dependency.

This means a single file can have `@dataflow:` blocks for initialization, a loop with `jump`, branching logic, and more `@dataflow:` blocks for post-processing -- all interleaved naturally.

### 2.3 The namespace/scope model

Namespaces (`label_name:` with an indented body) are the sole scoping and control-flow mechanism:

- During sequential execution, namespace definitions are **skipped**.
- Namespaces are only entered via `branch`, `switch`, `jump`, or `parallel`.
- When a namespace block ends, execution continues at the next line in the parent scope.
- All variables live in a **single flat scope** -- assignments inside namespaces are visible everywhere after assignment.

This model is intentionally simple. There is no block scoping, no closures, and no implicit returns. Loops are created by `jump`-ing back to an earlier namespace.

For full syntax and semantics, see [spec.md](spec.md).

---

## 3. kohakunode (Python)

Located at `src/kohakunode/`. Installable as the `kohakunode` package.

### 3.1 Module structure

```
src/kohakunode/
  __init__.py          Public API (all exports)
  errors.py            Exception hierarchy (KirError, KirSyntaxError, etc.)
  ast/
    nodes.py           All AST node dataclasses (Program, Statement, Expr, etc.)
    visitor.py         Visitor base class
  parser/
    parser.py          parse() / parse_file() -- Lark-based entry points
    transformer.py     Lark grammar transformer -> AST
  analyzer/
    validator.py       validate() / validate_or_raise() -> ValidationResult
    variables.py       Variable definition/use tracking
    scope.py           Namespace scope analysis
    errors.py          Analysis-specific errors
  compiler/
    dataflow.py        DataflowCompiler -- expand @dataflow: blocks (L2 -> L3)
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
    compiler.py        KirGraphCompiler -- L1 -> L2 (KirGraph -> Program AST)
    decompiler.py      KirGraphDecompiler -- L2 -> L1 (Program AST -> KirGraph)
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

### 3.2 Execution pipeline

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
        |  - Branch/Switch/Jump/Parallel: namespace control flow
        v
    VariableStore (final state)
```

### 3.3 Registry and execution

The `Registry` maps function names to `FunctionSpec` objects. A `FunctionSpec` holds the callable, input parameter names, output names, and default values. Input names and defaults are inferred from the function signature when not provided explicitly.

The `Executor` class orchestrates the full pipeline (validate, compile, interpret) and provides convenience methods like `execute_source()` and `execute_file()`. The module-level `run()` and `run_file()` functions are one-shot wrappers.

The `VariableStore` is a flat dictionary -- all variables live in one scope regardless of nesting depth.

### 3.4 Pluggable execution backend

The interpreter does not call registered functions directly. Instead, it delegates every function invocation to an `ExecutionBackend`. The default backend (`DefaultBackend`) preserves the original behavior -- a direct `func(**kwargs)` call. Users can substitute their own backend to add caching, logging, per-node persistent state, distributed dispatch, or any other execution strategy, without modifying the interpreter or the registered functions.

```
Interpreter                ExecutionBackend
    |                            |
    |-- on_node_enter(inv) ----->|
    |-- invoke(inv) ------------>|-- spec.func(**kwargs)
    |<--- result ----------------|
    |-- on_node_exit(inv, r, e)->|
```

Built-in backends: `DefaultBackend` (direct call), `CachingBackend` (memoization by input hash). Pass a backend via `Executor(backend=MyBackend())` or `run(source, backend=MyBackend())`.

---

## 4. kohakunode-rs (Rust)

Located at `src/kohakunode-rs/`. The Rust crate mirrors the Python implementation's core pipeline.

### 4.1 Dual build targets

The crate supports two build targets via Cargo features:

- **`python` (default)** -- builds a PyO3 native extension module via maturin. Python code imports it as `kohakunode_rs` to access fast Rust implementations of parsing, compilation, and layout.
- **`wasm`** -- builds a WASM module via wasm-bindgen. Used by the KIR Editor frontend for in-browser parsing, compilation, and layout without server round-trips.

The build script `scripts/build-wasm.sh` compiles to `wasm32-unknown-unknown` and runs `wasm-bindgen --target web` to produce JS glue in `kir-editor/frontend/src/wasm/`.

### 4.2 Module structure

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
    compiler.rs        KirGraphCompiler -- L1 -> L2
    decompiler.rs      KirGraphDecompiler -- L2 -> L1
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

### 4.3 WASM exports

The WASM module (`wasm_module.rs`) exposes these functions, all operating on JSON strings:

| Function | Input | Output | Purpose |
|---|---|---|---|
| `parse_kir(text)` | KIR source | Program AST JSON | Parse KIR to AST |
| `compile_dataflow(program_json)` | Program JSON | Program JSON | Expand `@dataflow:` blocks |
| `strip_meta(program_json)` | Program JSON | Program JSON | Remove `@meta` annotations |
| `compile_kirgraph(kirgraph_json)` | KirGraph JSON | Program JSON | L1 -> L2 compilation |
| `write_kir(program_json)` | Program JSON | KIR text | Serialize AST to KIR |
| `kir_to_graph(source)` | KIR source | KirGraph JSON | Extract graph from `.kir` |
| `auto_layout(graph_json)` | KirGraph JSON | KirGraph JSON | Assign node positions |
| `score_layout(graph_json)` | KirGraph JSON | `f64` | Layout quality score |
| `optimize_layout(graph_json, n)` | KirGraph JSON + iterations | KirGraph JSON | Improve layout |
| `decompile(program_json)` | Program JSON | KirGraph JSON | L2 -> L1 decompilation |

---

## 5. KIR Editor

The KIR Editor (`kir-editor/`) is a reference application showing KIR in action. It is a development and visualization tool, not the core product.

**Frontend** (`kir-editor/frontend/`): Vue 3, Vite, Pinia, Element Plus. Three views of the same graph -- a visual node editor, a block-based view, and a code editor with Monaco. The WASM module provides live IR preview and syntax validation entirely in the browser.

**Backend** (`kir-editor/backend/`): FastAPI application. Provides REST and WebSocket endpoints for KIR execution, node registration, and graph compilation/decompilation. Wraps the `kohakunode` Python engine.

See [api.md](api.md) for the kir-editor endpoint reference and the kohakunode library API.

---

## 6. Round-Tripping (L1 <-> L2)

Round-tripping is how KIR preserves visual graph structure through text.

### 6.1 Forward (L1 -> L2)

`KirGraphCompiler` emits `@meta node_id="<id>" pos=(x, y)` before every statement, recording which graph node each statement corresponds to and its visual position.

### 6.2 Reverse (L2 -> L1)

`KirGraphDecompiler` performs two passes:

1. **Node creation**: for each statement with `@meta node_id=...`, create a `KGNode`.
2. **Edge creation**: for each input identifier matching `{node_id}_{port}` of a known node, create a data edge. Control edges are reconstructed from the namespace/branch/switch/parallel topology.

The variable naming convention `{node_id}_{port_name}` (e.g., `add1_result`) is what makes decompilation reliable.

### 6.3 Graph extraction (`kir_to_graph`)

An alternative path: `kir_to_graph()` parses a `.kir` source and builds a `KirGraph` by tracking all variable definitions and usages directly from the AST. Unlike the decompiler, it handles plain variable names (not just `{node_id}_{port}` patterns). It also synthesizes merge nodes when multiple control edges converge on the same target.

---

## 7. Layout System

Located at `src/kohakunode/layout/` (Python) and `src/kohakunode-rs/src/layout/` (Rust). All components operate on `KirGraph` objects and require no running UI.

- **`auto_layout(graph)`** -- Fischer-style BFS: control chain runs vertically in column 0, data sources fan out left, data consumers fan out right. Cycle-aware.
- **`score_layout(graph)`** -- wire-bending quality metric. Lower is better. Penalizes column deviation for control edges, row deviation for data edges, plus crossing and overlap penalties.
- **`optimize_layout(graph, iterations)`** -- local-search improvement: iteratively tries row swaps, column moves, and row shifts, accepting any improvement.

---

## 8. ComfyUI Utilities

`src/kohakunode_utils/` -- installable as a separate package. Provides import and export between ComfyUI workflow JSON and KirGraph:

- `comfyui_to_kirgraph(workflow)` -- handles both workflow format (LiteGraph JSON) and API format (prompt JSON)
- `kirgraph_to_comfyui(graph)` -- reconstructs ComfyUI workflow from meta fields
- `comfyui_to_kir(workflow)` -- chains import, compile, and write for direct conversion

---

## 9. Tree-sitter Grammar

`tree-sitter-kir/` contains a tree-sitter grammar for KIR syntax, used for editor integrations. The `tree-sitter-kir/vscode/` subdirectory provides a VS Code extension with KIR syntax highlighting.
