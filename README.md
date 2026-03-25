# KohakuNodeIR

An intermediate representation language and toolchain that decouples node-based visual editors from their execution engines.

`.kir` files act as a portable interchange layer: any UI that can emit `.kir` can run on any conforming backend. The format handles both **control-flow** graphs (Scratch/Fischer-style: sequential, branch, loop) and **data-flow** graphs (ComfyUI/Blender-style: dependency-ordered) in one unified syntax — and you can mix them freely in the same file.

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
────────────────         ──────────────              ──────────────
nodes + edges            @dataflow: blocks           pure sequential
UI-native format         @meta annotations           no @dataflow:
no execution order       round-trippable to L1       engine-ready

     L1 → L2: KirGraphCompiler
     L2 → L3: DataflowCompiler + StripMetaPass
     L2 → L1: KirGraphDecompiler  (reads @meta, reconstructs topology)
```

L2 is the pivot format. The `@meta node_id="..." pos=(x, y)` annotations emitted by the compiler let any tool reconstruct the full visual graph from the text IR — no side-channel needed.

---

## Installation

Requires Python 3.10+ and [lark](https://github.com/lark-parser/lark).

```bash
git clone https://github.com/KohakuBlueLeaf/KohakuNodeIR.git
cd KohakuNodeIR
pip install -e .

# With ComfyUI converter utilities:
pip install -e ".[utils]"

# With dev/test dependencies:
pip install -e ".[dev]"
```

---

## Quick start

```bash
# Run examples
python examples/kir_basics/basic_math.py
python examples/kir_basics/control_flow.py
python examples/kirgraph_pipeline/demo.py

# ASCII graph viewer (works on .kir or .kirgraph)
python -m kohakunode.layout.ascii_view examples/kir_basics/mixed_mode.kir
```

```python
from kohakunode import Registry, run
from kohakunode import KirGraph, KirGraphCompiler, DataflowCompiler

# Execute a .kir program
registry = Registry()
registry.register("add",      lambda a, b: a + b,   output_names=["result"])
registry.register("multiply", lambda a, b: a * b,   output_names=["result"])
registry.register("print_val", lambda x: print(x),  output_names=[])

store = run("x = 10\ny = 20\n(x, y)add(sum)\n(sum)print_val()", registry=registry)

# Full L1 → L2 → L3 pipeline
graph = KirGraph.from_file("examples/kirgraph_pipeline/source.kirgraph")
l2    = KirGraphCompiler().compile(graph)   # L1 → L2 (.kir with @dataflow: + @meta)
l3    = DataflowCompiler().transform(l2)    # L2 → L3 (pure sequential)
run(l3, registry=registry)
```

---

## What's in the repo

| Package / directory | Purpose |
|---|---|
| `src/kohakunode/` | Core — IR parser, compiler, executor, layout |
| `src/kohakunode_viewer/` | Built-in static browser viewer (Vue 3 + Pyodide) |
| `src/kohakunode_utils/` | Built-in ComfyUI workflow import/export |
| `docs/` | Language spec, architecture, API reference |
| `examples/` | Runnable `.kir` programs and pipeline demos |
| `editors/vscode/` | VS Code syntax highlighting extension |
| `kir-editor/` | Example full-stack app (Vue 3 node editor + FastAPI server) |

### Python engine (`src/kohakunode/`)

```
kohakunode/
  ast/           AST node dataclasses
  parser/        Lark-based .kir parser
  compiler/      DataflowCompiler, StripMetaPass
  analyzer/      Semantic validator
  engine/        Executor, Interpreter, Registry, VariableStore
  kirgraph/      KirGraph schema, L1→L2 compiler, L2→L1 decompiler
  serializer/    AST reader and writer
  layout/        auto_layout, score, optimizer, ascii_view
  grammar/       Lark grammar file
```

### Layout system (`kohakunode.layout`)

Automatic graph layout for `.kirgraph` files, with no dependency on a running UI:

- **`auto_layout`** — Fischer-style BFS: control chain runs vertically in column 0, data sources fan out left, data consumers fan out right. Cycle-aware (back-edges are skipped during placement).
- **`score`** — wire-bending quality metric: control edges penalised for column deviation, data edges for row deviation, plus crossing and overlap penalties.
- **`optimizer`** — local-search improvement over `auto_layout`: iteratively tries row swaps, column moves, and row shifts, accepting any improvement.
- **`ascii_view`** — extract a `KirGraph` directly from any `.kir` source text (no `{node_id}_{port}` naming convention required), then print it as an ASCII grid.

```bash
python -m kohakunode.layout.ascii_view my_program.kir
```

Example output for `branching.kir` — nested if/else with data sources to the left, ctrl chain on the right:

```
  CONTROL EDGES (6):
    less_than_2.out ──ctrl──> branch_3.in
    branch_3.true ──ctrl──> print_4.in
    branch_3.false ──ctrl──> greater_than_5.in
    greater_than_5.out ──ctrl──> branch_6.in
    branch_6.true ──ctrl──> print_7.in
    branch_6.false ──ctrl──> print_8.in

  GRID LAYOUT (2 cols x 7 rows):

      |       col 0        |       col 1        |
      -------------------------------------------
  r 0 |      value_1       |    less_than_2     |
  r 1 |         ·          |      branch_3      |
  r 2 |         ·          |      print_4       |
  r 3 |         ·          |   greater_than_5   |
  r 4 |         ·          |      branch_6      |
  r 5 |         ·          |      print_7       |
  r 6 |         ·          |      print_8       |
      -------------------------------------------

  LAYOUT SCORE: 14.0 (lower = better)
```

A more complex example — `mixed_mode.kir` with `@dataflow:` blocks, a loop, and merge node:

```
  GRID LAYOUT (5 cols x 8 rows):

      |       col 0        |       col 1        |       col 2        |       col 3        |       col 4        |
      ----------------------------------------------------------------------------------------------------------
  r 0 |         ·          |     to_float_2     |         ·          |         ·          |         ·          |
  r 1 |         ·          |      merge_1       |         ·          |         ·          |         ·          |
  r 2 |      value_3       |       add_5        |    to_string_11    |     concat_12      |     concat_13      |
  r 3 |         ·          |     multiply_6     |         ·          |         ·          |         ·          |
  r 4 |      value_4       |       add_7        |         ·          |         ·          |         ·          |
  r 5 |     to_float_1     |    less_than_8     |         ·          |         ·          |         ·          |
  r 6 |         ·          |      branch_9      |         ·          |         ·          |         ·          |
  r 7 |         ·          |    to_string_10    |     concat_14      |      print_15      |         ·          |
      ----------------------------------------------------------------------------------------------------------
```

Col 1 is the control chain (top→bottom), col 0 has data sources (left of consumers), cols 2–4 have data consumers (right of sources).

### Static viewer (`src/kohakunode_viewer/`)

A zero-server browser app that accepts `.kir`, `.kirgraph`, and ComfyUI workflow JSON via file drop or paste. Parse paths:

- `.kirgraph` / ComfyUI JSON — parsed in JS directly
- `.kir` — first tries the real Python parser running in [Pyodide](https://pyodide.org/) (WASM), falls back to a JS lite parser

The Pyodide path runs `kir_to_graph` + `auto_layout` from the actual `kohakunode` package in-browser. The prebuild step copies the Python source files to `public/pylib/` so Pyodide can fetch and mount them at runtime.

The viewer also exposes a Python `generate_html()` function (`html_export.py`) that produces a fully self-contained single-file HTML visualisation of any `KirGraph` — no JS bundler, no CDN at render time (Pyodide is not used in the export).

### ComfyUI utilities (`src/kohakunode_utils/`)

```python
from kohakunode_utils.comfyui import comfyui_to_kirgraph
from kohakunode_utils.comfyui_export import kirgraph_to_comfyui
from kohakunode_utils.comfyui_to_kir import comfyui_to_kir

# Import: ComfyUI workflow JSON → KirGraph (L1)
graph = comfyui_to_kirgraph(workflow_dict)

# Export: KirGraph → ComfyUI workflow JSON (round-trip via stored meta)
workflow = kirgraph_to_comfyui(graph)

# Shortcut: ComfyUI → L2 KIR text
kir_text = comfyui_to_kir(workflow_dict)
```

Supports both ComfyUI workflow format (`nodes` + `links` arrays) and API/prompt format (`class_type` dicts). Widget values are mapped to input port defaults; `meta` fields store original slot info for lossless round-trips back to ComfyUI format.

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
# @dataflow: block — topologically sorted at compile time, inlined in L3
@dataflow:
    (product)finalize(output)
    (x, y)multiply(product)
    ()generate(y)

# @mode dataflow — whole-file toposort (no control flow allowed)
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
- [API Reference](docs/api.md) — backend REST and WebSocket endpoints
- [Getting Started](docs/getting_started.md) — editor setup and first graph

---

## License

Apache 2.0. Author: [KohakuBlueLeaf](https://kblueleaf.net/)
