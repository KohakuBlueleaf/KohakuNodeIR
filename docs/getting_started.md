# KohakuNodeIR -- Getting Started

This guide covers installing and using the kohakunode Python library, optionally enabling Rust acceleration, running the KIR Editor, and writing KIR by hand.

---

## 1. Using kohakunode (Python)

### Install

From the project root, create a virtual environment and install in editable mode:

```bash
git clone https://github.com/KohakuBlueLeaf/KohakuNodeIR.git
cd KohakuNodeIR
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

**Requirements:** Python 3.10+.

### Parse and execute

```python
from kohakunode import run, Registry

# Register your functions
registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])
registry.register("print", lambda value: print(value), output_names=[])

# Run a KIR program
store = run("x = 10\ny = 20\n(x, y)add(sum)\n(sum)print()", registry=registry)
# prints: 30
print(store.get("sum"))  # 30
```

### Register custom functions

```python
from kohakunode import Executor

executor = Executor()

# Method chaining
executor.register("add", lambda a, b: a + b, output_names=["result"])
executor.register("square", lambda x: x * x, output_names=["result"])

# Decorator style
@executor.register_decorator(output_names=["result"])
def multiply(a, b):
    return a * b

store = executor.execute_source("(3, 4)add(sum)\n(sum)square(y)")
print(store.get("y"))  # 49
```

### Work with the full pipeline

```python
from kohakunode import (
    parse, validate_or_raise, DataflowCompiler, StripMetaPass,
    Executor, Registry, KirGraphCompiler, KirGraph, Writer
)

# Load a .kirgraph and compile to L2 KIR
graph = KirGraph.from_json(open("graph.kirgraph").read())
program = KirGraphCompiler().compile(graph)
print(Writer().write(program))  # L2 text with @meta annotations

# Compile to L3 and execute
program = DataflowCompiler().transform(program)
program = StripMetaPass().transform(program)

registry = Registry()
# ... register functions ...
store = Executor(registry=registry).execute(program)
```

### Round-trip: decompile back to graph

```python
from kohakunode import parse, KirGraphDecompiler

program = parse(open("compiled_l2.kir").read())
graph = KirGraphDecompiler().decompile(program)
print(graph.to_json())
```

See [api.md](api.md) for the complete Python API reference.

---

## 2. Using kohakunode-rs (Optional Rust Acceleration)

The Rust crate provides fast implementations of parsing, compilation, and layout. It is optional -- the Python library works without it.

### Build the PyO3 module

**Requirements:** Rust 1.70+, maturin.

```bash
cd src/kohakunode-rs
pip install maturin
maturin develop --release
```

After building, you can import it directly:

```python
import kohakunode_rs

ast_json = kohakunode_rs.parse_kir("x = 10\n(x, 2)add(result)")
compiled = kohakunode_rs.compile_dataflow(ast_json)
stripped = kohakunode_rs.strip_meta(compiled)
```

All functions use a JSON bridge -- they accept and return JSON strings.

---

## 3. Running the KIR Editor (Optional Tool)

The KIR Editor is a visual node editor for exploring KIR. It is not required for using the kohakunode library.

### Prerequisites

| Requirement | Minimum version |
|-------------|-----------------|
| Python | 3.10 |
| Node.js | 18 |
| Rust | 1.70 |
| wasm-bindgen-cli | 0.2 |

### Build the WASM module

```bash
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli  # if not already installed
bash scripts/build-wasm.sh
```

### Install frontend dependencies

```bash
cd kir-editor/frontend
npm install
cd ../..
```

### Start the backend and frontend

In one terminal:

```bash
cd kir-editor && uvicorn backend.main:app --port 48888
```

In another terminal:

```bash
cd kir-editor/frontend && npm run dev
```

Open `http://localhost:5174` in your browser. The Vite dev server proxies `/api` requests to the backend.

---

## 4. Writing KIR by Hand

KIR programs are plain text files with a `.kir` extension. Here is a quick syntax overview -- see [spec.md](spec.md) for the full language specification.

### Assignments and function calls

```kir
x = 10
y = 20
(x, y)add(sum)
(sum)print()
```

### Branching

```kir
value = 42
(value, 0)less_than(is_negative)
(is_negative)branch(`handle_negative`, `handle_positive`)
handle_negative:
    ("negative")print()
handle_positive:
    ("positive or zero")print()
```

### Loops with jump

```kir
counter = 0
limit = 5
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep_going)
    (keep_going)branch(`continue_loop`, `exit_loop`)
    continue_loop:
        ()jump(`loop`)
    exit_loop:
(counter)print()
```

### Mixing dataflow and control flow

```kir
@dataflow:
    (10)to_float(limit)
    (0)to_float(counter)

()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep_going)
    (keep_going)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:

@dataflow:
    (counter)to_string(s)
    ("Counted to: ", s)concat(msg)
    (msg)print()
```

---

## 5. Running the Examples

The `examples/` directory contains runnable examples:

```bash
# Basic KIR examples (hello world, math, branching, loops, etc.)
cd examples/kir_basics
python run_all.py

# Full round-trip: .kirgraph -> L2 -> L3 -> execute -> decompile
cd examples/kirgraph_pipeline
python demo.py
```

Individual examples in `kir_basics/`:

| Script | What it demonstrates |
|--------|---------------------|
| `hello_world.py` | Hello, World! |
| `basic_math.py` | Simple arithmetic |
| `branching.py` | Conditional branching |
| `control_flow.py` | Loops with jump |
| `mixed_mode.py` | `@dataflow:` + control flow |
| `parallel_demo.py` | Parallel execution |
| `switch_demo.py` | Switch statement |
| `string_processing.py` | String operations |
| `subgraph_demo.py` | `@def` subgraph definitions |
| `data_pipeline.py` | Chained data processing |
