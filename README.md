# KohakuNodeIR

A visual node-based programming system built around the KIR intermediate representation. `.kir` files act as a portable interchange layer: any UI that can emit `.kir` can run on any conforming backend. The format handles both **control-flow** graphs (sequential, branch, loop) and **data-flow** graphs (dependency-ordered) in one unified syntax, and you can mix them freely in the same file.

---

## The language in 30 seconds

```kir
# Function call: (inputs)name(outputs)
x = 10
y = 20
(x, y)add(sum)
(sum, 3)multiply(product)
(product)print_val()
```

```kir
# Control flow: namespaces are skipped until entered via branch/jump/switch/parallel
counter = 0
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, 10)less_than(keep_going)
    (keep_going)branch(`loop`, `done`)
    done:
```

```kir
# Mixed: @dataflow: blocks are topologically sorted at compile time
@dataflow:
    (10)to_float(limit)
    (0)to_float(counter)

()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep)
    (keep)branch(`loop`, `done`)
    done:

@dataflow:
    (counter)to_string(s)
    ("Counted to: ", s)concat(msg)
    (msg)print()
```

---

## Three-level IR pipeline

```
.kirgraph (JSON)         .kir L2 (text)              .kir L3 (text)
----------------         --------------              --------------
nodes + edges            @dataflow: blocks           pure sequential
UI-native format         @meta annotations           no @dataflow:
no execution order       round-trippable to L1       engine-ready

     L1 -> L2: KirGraphCompiler
     L2 -> L3: DataflowCompiler + StripMetaPass
     L2 -> L1: KirGraphDecompiler  (reads @meta, reconstructs topology)
```

L2 is the pivot format. The `@meta node_id="..." pos=(x, y)` annotations emitted by the compiler let any tool reconstruct the full visual graph from the text IR -- no side-channel needed.

---

## Project structure

| Directory | Purpose |
|---|---|
| `src/kohakunode/` | Python library -- IR parser, compiler, executor, layout system |
| `src/kohakunode-rs/` | Rust core -- parser, compiler, layout, serializer. Builds as a PyO3 native module or as WASM via wasm-bindgen |
| `src/kohakunode_utils/` | ComfyUI workflow import/export utilities |
| `kir-editor/` | Full-stack visual editor: Vue 3 node editor frontend + FastAPI backend |
| `tree-sitter-kir/` | Tree-sitter grammar for KIR, plus a VS Code syntax highlighting extension |
| `docs/` | Language spec, architecture, API reference |
| `examples/` | Runnable `.kir` programs and pipeline demos |
| `scripts/` | Build scripts (e.g., `build-wasm.sh`) |

The three main components:

1. **Python library** (`src/kohakunode/`) -- the IR engine: Lark-based parser, dataflow compiler, interpreter, KirGraph schema, layout system. Installable as `pip install -e .`.

2. **Rust core + WASM** (`src/kohakunode-rs/`) -- a Rust reimplementation of the parser, compiler, layout, and serializer. Compiles to a native Python extension via PyO3/maturin, or to WebAssembly via wasm-bindgen for in-browser use. The WASM build replaces the former Pyodide approach and provides the frontend with instant KIR parsing, compilation, and layout without a server round-trip.

3. **KIR Editor** (`kir-editor/`) -- a Vue 3 node editor (Vite, Pinia, Element Plus, UnoCSS) backed by a FastAPI execution server. The frontend uses the WASM module for live IR preview and validation, and communicates with the backend via REST/WebSocket for execution and node management.

---

## Quick start

### Prerequisites

| Requirement | Minimum version |
|---|---|
| Python | 3.10 |
| Node.js | 18 |
| Rust | 1.70 (for WASM build) |

### 1. Install the Python engine

```bash
git clone https://github.com/KohakuBlueLeaf/KohakuNodeIR.git
cd KohakuNodeIR
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 2. Build the WASM module

```bash
bash scripts/build-wasm.sh
```

This compiles the Rust crate to `wasm32-unknown-unknown` and runs `wasm-bindgen` to produce JS glue in `kir-editor/frontend/src/wasm/`.

### 3. Install frontend dependencies

```bash
cd kir-editor/frontend && npm install
```

### 4. Run the editor

Start the backend (from the project root):

```bash
cd kir-editor && uvicorn backend.main:app --port 48888
```

Start the frontend dev server (in a second terminal):

```bash
cd kir-editor/frontend && npm run dev
```

Open `http://localhost:5174` in your browser.

---

## Key features

### Code node

A new node type with an embedded Monaco editor for writing inline KIR code directly in the graph. The WASM parser validates syntax in real time, underlining errors as you type.

### Custom node system

Define new node types through the Node Definition Editor in the UI or via the REST API. Custom nodes support **property schemas** with typed widgets:

- **string** -- text input
- **number** -- numeric input
- **boolean** -- checkbox
- **select** -- dropdown with custom choices
- **slider** -- range slider with min/max/step

Property defaults are persisted to disk and synced between the frontend and backend.

### Output panel

The IR Preview panel shows live-compiled KIR L2, L3, and KirGraph JSON tabs. The execution output includes a **collapsible Variables accordion** that lists the final variable store after each run.

---

## Python API

```python
from kohakunode import Registry, run
from kohakunode import KirGraph, KirGraphCompiler, DataflowCompiler

# Execute a .kir program
registry = Registry()
registry.register("add",      lambda a, b: a + b,   output_names=["result"])
registry.register("multiply", lambda a, b: a * b,   output_names=["result"])
registry.register("print_val", lambda x: print(x),  output_names=[])

store = run("x = 10\ny = 20\n(x, y)add(sum)\n(sum)print_val()", registry=registry)

# Full L1 -> L2 -> L3 pipeline
graph = KirGraph.from_file("examples/kirgraph_pipeline/source.kirgraph")
l2    = KirGraphCompiler().compile(graph)   # L1 -> L2 (.kir with @dataflow: + @meta)
l3    = DataflowCompiler().transform(l2)    # L2 -> L3 (pure sequential)
run(l3, registry=registry)
```

---

## Language reference

### Function calls and assignments

```kir
x = 42
(x, "label")process(result, _)    # _ discards an output
(x, mode="fast")compute(out)      # keyword arguments
```

### Control flow

```kir
# branch
(cond)branch(`on_true`, `on_false`)

# switch
(status)switch(0=>`idle`, 1=>`running`, _=>`error`)

# loop (jump + branch back)
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, 10)less_than(keep)
    (keep)branch(`loop`, `done`)
    done:

# parallel (order between branches unspecified; both complete before resuming)
()parallel(`task_a`, `task_b`)
task_a:
    (data)process_a(result_a)
task_b:
    (data)process_b(result_b)
```

### Dataflow

```kir
# @dataflow: block -- topologically sorted at compile time, inlined in L3
@dataflow:
    (product)finalize(output)
    (x, y)multiply(product)
    ()generate(y)

# @mode dataflow -- whole-file toposort (no control flow allowed)
@mode dataflow
(b, c)add(a)
(c)generate(c)
```

### Subgraphs

```kir
@def (a, b)clamp(result):
    (a, b)min_val(lo)
    (a, b)max_val(hi)
    (lo, hi)add(sum)
    (sum, 2)divide(result)

(x, y)clamp(avg)
```

### Round-trip metadata

```kir
@meta node_id="n01" pos=(120, 300) size=[180, 120]
(x)process(y)
```

`@meta` lines are ignored by the executor and used by `KirGraphDecompiler` to reconstruct the full visual graph from L2 text.

---

## Documentation

- [Language Specification](docs/spec.md)
- [KirGraph Format](docs/kirgraph_spec.md)
- [Architecture](docs/architecture.md)
- [API Reference](docs/api.md) -- backend REST and WebSocket endpoints
- [Getting Started](docs/getting_started.md) -- editor setup and first graph

---

## License

Apache 2.0. Author: [KohakuBlueLeaf](https://kblueleaf.net/)
