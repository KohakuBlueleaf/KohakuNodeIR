# KohakuNodeIR

<!-- TODO: banner image -->

**A text-based intermediate representation for visual programming.**

<!-- TODO: badges (build, license, pypi, Python version) -->

KIR is a language that sits between visual programming editors and execution engines.
It captures both control flow and dataflow in one file, round-trips cleanly between
text and graph representations, and runs on any conforming backend.

<!-- TODO: editor screenshot showing the three-view interface -->

---

## What is KIR?

KIR (Kohaku Intermediate Representation) is a text IR designed for visual programming
systems — both node-based editors and block-based (Scratch-like) environments. It
solves a common problem: visual editors produce graph structures, but you need a
serializable, diff-friendly, human-readable format to store, version, and execute them.

A `.kir` file can express:
- **Sequential control flow** — statements execute top to bottom
- **Branching and looping** — `branch`, `switch`, `jump`, `parallel`
- **Dataflow** — `@dataflow:` blocks where execution order is determined by data dependencies
- **Mixed mode** — control flow and dataflow in the same program

The same `.kir` file can be viewed as a node graph, as nested blocks, or as plain text.
Any editor that emits `.kir` can target any engine that consumes it — the IR is the
contract between them.

## Language Features

- **Mixed control-flow and data-flow** — combine sequential execution with
  dependency-ordered blocks in one file
- **Scoped `@dataflow:` blocks** — opt into dataflow ordering for specific sections
  while keeping the rest sequential
- **Namespaces** — labeled scopes (`label:`) for jump targets and structure
- **`@def` subgraph definitions** — reusable parameterized subgraphs, like functions
- **Control-flow primitives** — `branch` (if/else), `switch` (multi-case),
  `jump` (goto/loop), `parallel` (concurrent branches)
- **`@meta` annotations** — attach node positions, IDs, and sizes to statements;
  these survive text↔graph roundtrips so your layout is preserved
- **Three-level IR pipeline** — L1 (JSON graph) → L2 (text with @meta) → L3
  (clean sequential, engine-ready)
- **Function-call syntax** — `(inputs)func_name(outputs)` is concise and
  maps directly to node wiring

## The Language in 30 Seconds

```kir
# Dataflow block: order determined by data dependencies, not line order
@dataflow:
    (10)to_float(limit)
    (0)to_float(counter)

# Sequential control flow: explicit loop
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep_going)
    (keep_going)branch(`loop`, `done`)
    done:
        (counter)to_string(s)
        ("Counted to: ", s)concat(msg)
        (msg)print()
```

Key syntax patterns:
- **Assignment**: `x = 42`
- **Function call**: `(a, b)add(result)` — inputs on left, outputs on right
- **Label reference**: `` `loop` `` — backtick-quoted reference to a namespace
- **Metadata**: `@meta node_id="n1" pos=(100, 200)` — preserved through roundtrips
- **Dataflow scope**: `@dataflow:` block auto-orders by data dependencies

See the full [Language Specification](docs/spec.md) for details.

---

## Three-Level IR Pipeline

KIR uses three representations at different stages:

| Level | Format | Purpose | Example |
|-------|--------|---------|---------|
| **L1** | `.kirgraph` (JSON) | Visual editors native format — flat list of nodes and edges | `{"nodes": [...], "edges": [...]}` |
| **L2** | `.kir` (text) | Human-readable IR with `@meta` annotations — round-trip safe | `@meta node_id="n1" pos=(100,200)` |
| **L3** | `.kir` (text) | Pure sequential — metadata stripped, dataflow expanded | Ready for execution |

Compilation: L1 → L2 → L3. Decompilation: L2 → L1. The `@meta` annotations in L2
are what make this round-trip possible — they carry the graph layout information
through the text representation.

---

## Implementations

| Package | Language | Role |
|---------|----------|------|
| **kohakunode** | Python | Reference implementation — Lark parser, AST, compiler passes, interpreter, layout engine |
| **kohakunode-rs** | Rust | Fast reimplementation — pest parser, compiler, layout, serializer. Builds as PyO3 native module or WASM for browsers |

Both implementations produce identical output for the same input — the Python
version is the ground truth, and the Rust version must match exactly.

### Quick Start (Python)

```bash
git clone https://github.com/KohakuBlueleaf/KohakuNodeIR.git
cd KohakuNodeIR
pip install -e .
```

```python
from kohakunode import Registry, Executor

# Register custom functions
registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])
registry.register("print_val", lambda x: print(x), output_names=[])

# Execute KIR source
executor = Executor(registry=registry)
store = executor.execute_source("""
x = 10
y = 20
(x, y)add(sum)
(sum)print_val()
""")
# Output: 30
```

### Optional: Rust Acceleration

```bash
cd src/kohakunode-rs
maturin develop --release   # installs kohakunode_rs as Python module
```

Once installed, `import kohakunode_rs` provides the same functions as the Python
library but runs significantly faster. The Python library auto-detects it via
`kohakunode._rust.HAS_RUST`.

---

## Tools

These are utilities built on top of the KIR language and libraries:

### KIR Editor (`kir-editor/`)

A full-stack visual editor for building and running KIR programs. Three views of
the same program:
- **Node Graph** — drag-and-drop visual wiring
- **Blocks** — Scratch-like nested block view
- **Code** — Monaco editor with KIR syntax highlighting

The frontend uses WASM-compiled `kohakunode-rs` for instant in-browser parsing
and compilation (no server round-trip for editing). The backend (FastAPI) handles
execution and custom node registration.

```bash
# Build WASM module
bash scripts/build-wasm.sh

# Start backend (port 48888)
cd kir-editor && uvicorn backend.main:app --port 48888

# Start frontend (port 5174, separate terminal)
cd kir-editor/frontend && npm install && npm run dev
```

### Tree-sitter Grammar (`tree-sitter-kir/`)

Syntax highlighting for `.kir` files. Includes a VS Code extension:

```bash
ln -s $(pwd)/tree-sitter-kir/vscode ~/.vscode/extensions/kir-language
```

---

## Project Structure

```
KohakuNodeIR/
├── src/
│   ├── kohakunode/          # Python library: parser, compiler, executor, layout
│   ├── kohakunode-rs/       # Rust core: parser, compiler, layout (PyO3 + WASM)
│   └── kohakunode_utils/    # ComfyUI workflow import/export
├── kir-editor/              # Visual editor (Vue 3 frontend + FastAPI backend)
│   ├── frontend/            # Vue 3 + Vite + Monaco + WASM
│   └── backend/             # FastAPI execution server
├── tree-sitter-kir/         # Tree-sitter grammar + VS Code extension
├── docs/                    # Language spec, architecture, API reference
├── examples/                # Runnable .kir programs and pipeline demos
├── tests/                   # Python test suite
└── scripts/                 # Build scripts (WASM, etc.)
```

## Documentation

| Document | Description |
|----------|-------------|
| [Language Specification](docs/spec.md) | Full KIR syntax, KirGraph JSON format, and IR pipeline rules |
| [Architecture](docs/architecture.md) | System design, component relationships, execution model |
| [API Reference](docs/api.md) | kohakunode Python API, kohakunode-rs Rust/WASM API |
| [Getting Started](docs/getting_started.md) | Installation, first program, editor setup |
| [Examples](examples/) | 10+ runnable programs: basics, pipelines, ComfyUI conversion |
| [Layout Research](docs/layout_research.md) | Auto-layout algorithm design and academic references |

## Contributing

<!-- TODO: CONTRIBUTING.md -->

Contributions welcome. Please open an issue before starting significant work so
we can discuss the approach.

## License

[Apache 2.0](LICENSE)

Author: [KohakuBlueLeaf](https://kblueleaf.net/)
