# KohakuNodeIR

> A portable IR language and toolchain that bridges node-based visual editors with execution engines.

KohakuNodeIR (`.kir`) is an intermediate representation designed for node-based visual programming systems. It acts as a portable middleware layer: node UIs compile their graphs into `.kir`, and any conforming backend can execute it — no tight coupling between editor and engine.

The language handles both **control-flow** style programming (sequential, branching, looping — like Scratch or Lego Mindstorms) and **data-flow** style programming (dependency-ordered execution — like ComfyUI or the Blender node editor) in a single unified format.

---

## Key Features

- **Dual paradigm** — control-flow and data-flow in one IR; mix them freely within a single file
- **Three-level architecture** — `.kirgraph` (graph topology) → `.kir` L2 (human-readable) → `.kir` L3 (execution-ready)
- **Round-trippable** — `@meta` annotations let UIs reconstruct exact visual layout from IR text
- **No built-in functions** — zero domain functions are baked in; all resolution is backend-provided
- **Reusable subgraphs** — `@def` blocks define named node groups, callable like any function
- **Parallel execution** — `parallel` primitive marks independent branches with no ordering guarantee
- **Vue 3 node editor** — visual graph editor included (`app/frontend/`)
- **Python engine** — parser, validator, compiler, and executor in `src/kohakunode/`
- **424 tests** across 22 test files

---

## Quick Example

A simple arithmetic program in `.kir`:

```kir
x = 10
y = 20
(x, y)add(sum)
(sum, 3)multiply(product)
(product)print_val()
```

Function call syntax is `(inputs)function_name(outputs)`. Inputs are comma-separated variable names or literals. Outputs are variable names to bind the results to. Use `_` to discard an output.

A factorial loop using control flow:

```kir
# Factorial of 5
n = 5
result = 1
counter = 1

()jump(`loop`)
loop:
    (result, counter)multiply(result)
    (counter, 1)add(counter)
    (counter, n)less_equal(keep_going)
    (keep_going)branch(`continue_loop`, `done`)
    continue_loop:
        ()jump(`loop`)
    done:

(n, result)format_factorial(msg)
(msg)print_val()
```

Namespaces are **skipped on encounter** and entered only via `branch`, `switch`, `jump`, or `parallel`. This makes all control flow explicit and traceable.

---

## Three-Level IR

KohakuNodeIR uses a three-level pipeline. Each level serves a distinct purpose:

```
L1: .kirgraph       L2: .kir (with @dataflow:, @meta)    L3: .kir (pure sequential)
JSON graph           human-readable, round-trippable        engine-ready, no @dataflow:
```

| Level | Format | Purpose |
|-------|--------|---------|
| L1 | `.kirgraph` (JSON) | Graph topology from the node UI — nodes, edges, positions |
| L2 | `.kir` (text) | Interchange format — `@dataflow:` scopes, `@meta` annotations, control flow |
| L3 | `.kir` (text) | Execution format — pure sequential statements, `@dataflow:` blocks expanded |

**L2 is the pivot.** It can convert in both directions: to L1 for the UI, and to L3 for execution.

### Pipeline trace — the same program at each level

**L1 source** (`examples/kirgraph_pipeline/source.kirgraph`, abbreviated):

```json
{
  "version": "0.1.0",
  "nodes": [
    { "id": "val_limit", "type": "value", "properties": { "value": 3 }, ... },
    { "id": "inc_i",     "type": "add",   ... },
    { "id": "branch",    "type": "branch", ... }
  ],
  "edges": [
    { "type": "data",    "from": { "node": "val_limit", "port": "value" }, "to": { "node": "check", "port": "b" } },
    { "type": "control", "from": { "node": "branch",    "port": "true"  }, "to": { "node": "merge_loop", "port": "back" } }
  ]
}
```

**L2 output** (compiled, with `@dataflow:` and `@meta`):

```kir
@dataflow:
    @meta node_id="val_limit" pos=(100, 100) size=[160, 100]
    val_limit_value = 3
    @meta node_id="val_i" pos=(100, 380) size=[160, 100]
    val_i_value = 0
    @meta node_id="val_total" pos=(100, 520) size=[160, 100]
    val_total_value = 0
@meta node_id="merge_loop" pos=(340, -20) size=[140, 100]
()jump(`ns_merge_loop`)
ns_merge_loop:
    @meta node_id="inc_i" pos=(320, 100) size=[180, 120]
    (val_i_value, val_step_value)add(inc_i_result)
    @dataflow:
        @meta node_id="square" pos=(520, 100) size=[180, 120]
        (inc_i_result, inc_i_result)multiply(square_result)
        @meta node_id="accum" pos=(720, 100) size=[180, 120]
        (val_total_value, square_result)add(accum_result)
@meta node_id="branch" pos=(920, 280) size=[180, 120]
(check_result)branch(`branch_true`, `branch_false`)
branch_true:
    ()jump(`ns_merge_loop`)
branch_false:
    (accum_result)to_string(to_str_result)
    ("Sum of squares = ", to_str_result)concat(fmt_result)
    (fmt_result)print()
```

**L3 output** (execution-ready, `@dataflow:` expanded, `@meta` stripped):

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
(inc_i_result, val_limit_value)less_than(check_result)
(check_result)branch(`branch_true`, `branch_false`)
branch_true:
    ()jump(`ns_merge_loop`)
branch_false:
    (accum_result)to_string(to_str_result)
    ("Sum of squares = ", to_str_result)concat(fmt_result)
    (fmt_result)print()
```

---

## Architecture

```
Node UI (Vue 3)
    |
    | edit / save
    v
.kirgraph  (L1 — JSON graph topology)
    |
    | KirGraphCompiler  (L1 → L2)
    v
.kir L2    (human-readable IR, @dataflow: + @meta)
    |   \
    |    \  KirGraphDecompiler  (L2 → L1, round-trip)
    |     \-----> .kirgraph
    |
    | DataflowCompiler + StripMetaPass  (L2 → L3)
    v
.kir L3    (pure sequential, engine-ready)
    |
    | Executor + Registry
    v
  Output
```

---

## Getting Started

**Requirements:** Python 3.10+, [lark](https://github.com/lark-parser/lark)

```bash
git clone https://github.com/KohakuBlueLeaf/KohakuNodeIR.git
cd KohakuNodeIR
pip install -e .
```

**Run an example:**

```bash
python examples/kir_basics/basic_math.py
python examples/kir_basics/control_flow.py
python examples/kirgraph_pipeline/demo.py
```

**Use the Python API:**

```python
import kohakunode as kir

# Register backend functions
registry = kir.Registry()
registry.register("add",      lambda a, b: (a + b,))
registry.register("multiply", lambda a, b: (a * b,))
registry.register("print_val", lambda x: (print(x), None)[1:])

# Parse and run a .kir file
program = kir.parse_file("examples/kir_basics/basic_math.kir")
kir.run(program, registry)

# Or compile a .kirgraph through the full pipeline
graph   = kir.KirGraph.from_file("examples/kirgraph_pipeline/source.kirgraph")
l2      = kir.KirGraphCompiler().compile(graph)          # L1 → L2
l3      = kir.DataflowCompiler().compile(l2)             # L2 → L3
kir.run(l3, registry)
```

**Run the test suite:**

```bash
pip install -e ".[dev]"
pytest tests/
```

---

## Project Structure

```
KohakuNodeIR/
├── src/kohakunode/         # Python IR engine
│   ├── ast/                # AST node definitions
│   ├── parser/             # Lark-based .kir parser
│   ├── engine/             # Executor, interpreter, registry, variable store
│   ├── compiler/           # DataflowCompiler, StripMetaPass
│   ├── analyzer/           # Validator
│   ├── kirgraph/           # L1 schema, compiler (L1→L2), decompiler (L2→L1)
│   ├── serializer/         # Reader (parse from string/file) and Writer
│   ├── grammar/            # Lark grammar file
│   └── errors.py           # KirError hierarchy
├── app/
│   ├── frontend/           # Vue 3 node editor
│   └── backend/            # FastAPI server
├── docs/
│   ├── spec.md             # Language specification
│   ├── kirgraph_spec.md    # KirGraph format specification
│   ├── architecture.md     # System architecture reference
│   ├── api.md              # Backend REST and WebSocket API reference
│   ├── getting_started.md  # Installation and first-run guide
│   ├── example.kir         # Full-feature .kir example
│   └── scoped_dataflow_example.kir  # Mixed control-flow + dataflow example
├── examples/
│   ├── kir_basics/         # .kir programs with Python runners
│   └── kirgraph_pipeline/  # Full L1→L2→L3 pipeline demo
├── editors/
│   └── vscode/             # VS Code extension (syntax highlighting)
└── tests/                  # 424 tests across 22 files
```

---

## Language Features

### Assignments and function calls

```kir
x = 42
name = "hello"
(x, name)process(result, _)         # _ discards an output
(x, mode="fast")compute(out)        # keyword arguments
```

### Branch and switch

```kir
(condition)branch(`on_true`, `on_false`)
on_true:
    (x)handle_true(y)
on_false:
    (x)handle_false(y)

# Switch on a value
(status)switch(0=>`idle`, 1=>`running`, _=>`error`)
```

### Loops with jump and merge

```kir
counter = 0
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, 10)less_than(keep_going)
    (keep_going)branch(`loop`, `done`)
    done:
```

### Parallel execution

```kir
()parallel(`task_a`, `task_b`)
task_a:
    (data, " + processed_A")concat(result_a)
    (result_a)print()
task_b:
    (data, " + processed_B")concat(result_b)
    (result_b)print()
# resumes here after both complete
```

`parallel` guarantees both branches complete before execution continues. The backend may run them concurrently or in any order.

### Scoped @dataflow: blocks

```kir
# Order is resolved by data dependencies, not line order
@dataflow:
    (product)finalize(output)
    (x, y)multiply(product)
    ()generate(y)
```

A `@dataflow:` block is topologically sorted at compile time and inlined as sequential statements in L3.

### @def subgraph definitions

```kir
@def (a, b)clamp(result):
    (a, b)min_val(lo)
    (a, b)max_val(hi)
    (lo, hi)add(sum)
    (sum, 2)divide(result)

# Call it like any function
(x, y)clamp(avg)
(x, y, strength=2.0)clamp(avg2)
```

Subgraphs are reusable node groups — equivalent to custom blocks in Scratch or node groups in Blender.

### @meta annotations (round-trip support)

```kir
@meta node_id="n01" pos=(120, 300) size=[180, 120]
@meta color="blue" label="My Processing Node"
(x)process(y)
```

`@meta` lines attach UI metadata to the next statement. The executor ignores them entirely. The decompiler uses them to reconstruct graph topology and layout from L2 IR.

### Mixed control-flow and data-flow

```kir
# Dataflow initialization (order resolved by deps)
@dataflow:
    (10)to_float(limit)
    (0)to_float(counter)

# Control flow loop
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep)
    (keep)branch(`loop`, `done`)
    done:

# Dataflow post-processing
@dataflow:
    (counter)to_string(s)
    ("Counted to: ", s)concat(msg)
    (msg)print()
```

---

## Documentation

- [Language Specification](docs/spec.md) — full grammar, execution model, namespace rules, built-in utilities, dataflow semantics
- [KirGraph Format](docs/kirgraph_spec.md) — L1 JSON schema, node/edge definitions, compilation rules, full pipeline example
- [Architecture](docs/architecture.md) — system architecture, module structure, execution pipeline
- [API Reference](docs/api.md) — backend REST and WebSocket endpoints
- [Getting Started](docs/getting_started.md) — installation, running the editor, first graph walkthrough
- [Examples](examples/) — runnable `.kir` programs covering all language features

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

Author: [KohakuBlueLeaf](https://kblueleaf.net/)
