# KohakuNodeIR — Getting Started

This guide walks through installing the project, running the frontend and backend, and building and executing your first node graph.

---

## Prerequisites

| Requirement | Minimum version | Notes |
|-------------|-----------------|-------|
| Python | 3.10 | Required for `match` syntax and modern type hints |
| Node.js | 18 | Required by Vite and the frontend build |
| npm | 9 | Comes with Node.js 18+ |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourorg/KohakuNodeIR.git
cd KohakuNodeIR
```

### 2. Install the Python engine

From the project root:

```bash
pip install -e .
```

This installs the `kohakunode` package in editable mode. The backend server depends on it.

Install backend dependencies:

```bash
pip install fastapi uvicorn
```

Or if a `requirements.txt` exists in `app/backend/`:

```bash
pip install -r app/backend/requirements.txt
```

### 3. Install frontend dependencies

```bash
cd app/frontend
npm install
cd ../..
```

---

## Running the System

You need two processes: the backend server and the frontend dev server.

### Start the backend

```bash
cd app/backend
python main.py
```

The backend starts at `http://localhost:48888`. You should see uvicorn startup output:

```
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:48888
```

### Start the frontend dev server

In a separate terminal:

```bash
cd app/frontend
npm run dev
```

The dev server starts at `http://localhost:5174`. Open that URL in your browser.

The Vite dev server proxies all `/api` requests to the backend, so you only need to talk to port `5174` from the browser.

---

## The Node Editor Interface

When you open `http://localhost:5174` you will see:

- **Left panel — Node Palette**: All available node types grouped by category. Click and drag a node type onto the canvas to create it.
- **Center — Editor Canvas**: The main graph editing area. Pan with middle-click drag or right-click drag. Zoom with the scroll wheel.
- **Right panel — Property Panel**: When a node is selected, edit its properties here (e.g., the literal value of a Value node).
- **Bottom panel — IR Preview**: Live preview of the KIR text generated from the current graph. Collapses/expands.
- **Toolbar**: Zoom controls, undo/redo, mode toggle (control-flow / dataflow), save/load.

---

## Creating Your First Graph

This example builds a simple program: add two numbers and print the result.

### Step 1: Add a Value node for the first number

1. In the Node Palette, find **Value** (under the "value" category or search for it).
2. Drag it onto the canvas.
3. Select it; in the Property Panel set `value` to `10` and `valueType` to `int`.

### Step 2: Add a second Value node

Repeat for a second Value node with value `20`.

### Step 3: Add an Add node

Drag an **add** node onto the canvas. It has two data inputs (`a`, `b`) and one data output (`result`).

### Step 4: Connect data wires

Data ports appear as circles on the left (inputs) and right (outputs) of each node.

1. Click the output port (right side) of the first Value node and drag to the `a` input of the Add node.
2. Click the output port of the second Value node and drag to the `b` input of the Add node.

The wires are now drawn as bezier curves in blue (data wires).

### Step 5: Add a Print node

Drag a **print** node onto the canvas. Connect the `result` output of the Add node to the `value` input of the Print node.

### Step 6: Connect control wires

Control ports appear at the top (inputs) and bottom (outputs) of nodes that have them. For a pure control-flow graph, the Add and Print nodes need to be connected in sequence.

1. Click the control output (bottom) of the Add node.
2. Drag to the control input (top) of the Print node.

Control wires appear in orange/red.

Note: Value nodes have no control ports — they are "data-only" and will be compiled into a `@dataflow:` block automatically.

### Step 7: View the IR

Open the **IR Preview** panel at the bottom. You should see something like:

```kir
@dataflow:
    @meta node_id="node-..." pos=(...)
    v_abc12345_value = 10
    @meta node_id="node-..." pos=(...)
    v_def67890_value = 20
@meta node_id="node-..." pos=(...)
(v_abc12345_value, v_def67890_value)add(v_ghi11111_result)
@meta node_id="node-..." pos=(...)
(v_ghi11111_result)print()
```

---

## Executing a Graph

### Option A: Via the IR Preview

1. Open the IR Preview panel.
2. Click the **Execute** button inside the panel (if present), or copy the KIR text.

### Option B: Via the REST API directly

Copy the KIR text from the IR Preview, then send it to the backend:

```bash
curl -s -X POST http://localhost:48888/api/execute \
  -H "Content-Type: application/json" \
  -d '{"kir_source": "x = 10\ny = 20\n(x, y)add(sum)\n(sum)print()"}'
```

Response:

```json
{
  "success": true,
  "variables": { "x": 10, "y": 20, "sum": 30 },
  "output": [{ "type": "output", "value": "30" }]
}
```

### Option C: Via Python

```python
from kohakunode import run, Registry

registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])
registry.register("print", lambda value: print(value), output_names=[])

store = run("x = 10\ny = 20\n(x, y)add(sum)\n(sum)print()", registry=registry)
```

---

## Saving and Loading Graphs

### Save as .kirgraph

Click **Save** in the toolbar. The browser downloads a `graph.kirgraph` file (JSON format). This is the Level 1 IR — it stores the complete graph topology including node positions.

### Load a .kirgraph

Click **Load** in the toolbar and select a `.kirgraph` file. The graph store is replaced with the loaded graph.

### What is saved

The `.kirgraph` file contains:
- All nodes with their types, port definitions, property values, and canvas positions
- All edges (data and control connections)

What is NOT saved: the current zoom/pan state of the canvas.

### Programmatic round-trip

```python
from kohakunode import KirGraph, KirGraphCompiler, KirGraphDecompiler, parse
from kohakunode.serializer.writer import Writer

# Load a .kirgraph
graph = KirGraph.from_json(open("my_graph.kirgraph").read())

# Compile to L2 KIR
program = KirGraphCompiler().compile(graph)
kir_text = Writer().write(program)
print(kir_text)

# Decompile back to .kirgraph
graph2 = KirGraphDecompiler().decompile(program)
print(graph2.to_json())
```

---

## Registering a Custom Node

### Via the UI

1. Click the **+** button in the Node Palette (or open Node Definition Editor from the menu).
2. Fill in:
   - **Name**: Display name (e.g., "Square")
   - **Type**: Unique identifier (e.g., `square`) — this is the function name used in KIR
   - **Category**: Groups nodes in the palette
   - **Inputs / Outputs**: Port definitions
   - **Code**: Python function body
3. Click Save. The node appears in the palette immediately and is persisted to the backend.

Example node code:

```python
def node_func(value):
    return value * value
```

For multiple outputs, return a tuple in the same order as the declared outputs:

```python
def node_func(a, b):
    return a + b, a - b
```

### Via the REST API

```bash
curl -s -X POST http://localhost:48888/api/nodes/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Square",
    "type": "square",
    "category": "math",
    "description": "Computes value squared.",
    "inputs": [{"name": "value", "type": "float"}],
    "outputs": [{"name": "result", "type": "float"}],
    "code": "def node_func(value):\n    return value * value"
  }'
```

---

## Writing KIR by Hand

If you want to write `.kir` programs directly without the UI:

### Minimal example

```kir
# basic_math.kir
x = 10
y = 20
(x, y)add(sum)
(sum, 3)multiply(product)
(product)print()
```

Execute it:

```bash
curl -s -X POST http://localhost:48888/api/execute \
  -H "Content-Type: application/json" \
  --data-raw '{"kir_source": "x = 10\ny = 20\n(x, y)add(sum)\n(sum, 3)multiply(product)\n(product)print()"}'
```

Or with the Python API:

```python
from kohakunode import run_file
from kohakunode import Registry

registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])
registry.register("multiply", lambda a, b: a * b, output_names=["result"])
registry.register("print", lambda value: print(value), output_names=[])

run_file("basic_math.kir", registry=registry)
```

### Branching example

```kir
value = 42
(value, 0)less_than(is_negative)
(is_negative)branch(`handle_negative`, `handle_positive`)
handle_negative:
    ("negative")print()
handle_positive:
    ("positive or zero")print()
```

### Loop example

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

### Mixed dataflow and control flow

```kir
# Initialize with dataflow
@dataflow:
    (10)to_float(limit)
    (0)to_float(counter)

# Run a loop
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep_going)
    (keep_going)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:

# Post-process with dataflow
@dataflow:
    (counter)to_string(s)
    ("Counted to: ", s)concat(msg)
    (msg)print()
```

---

## Running the Examples

The `examples/` directory contains runnable examples.

### kir_basics

```bash
cd examples/kir_basics
python run_all.py
```

This runs all `.kir` examples in the directory and prints their outputs.

Individual examples:

```bash
python basic_math.py          # simple arithmetic
python branching.py           # conditional branching
python control_flow.py        # loops with jump
python mixed_mode.py          # @dataflow: + control flow
python parallel_demo.py       # parallel execution
python switch_demo.py         # switch statement
python string_processing.py   # string operations
python subgraph_demo.py       # @def subgraph definitions
python data_pipeline.py       # chained data processing
```

### kirgraph_pipeline

Full round-trip demo: `.kirgraph` → L2 KIR → L3 KIR → execution → decompile back to `.kirgraph`.

```bash
cd examples/kirgraph_pipeline
python demo.py
```

The source graph is `source.kirgraph`. Compiled outputs are `compiled_l2.kir` and `compiled_l3.kir`. The decompiled round-trip result is `decompiled.kirgraph`.

---

## Keyboard Shortcuts (Editor)

| Shortcut | Action |
|----------|--------|
| Delete / Backspace | Delete selected nodes and connections |
| Ctrl+Z | Undo |
| Ctrl+Y / Ctrl+Shift+Z | Redo |
| Ctrl+A | Select all nodes |
| Escape | Deselect all / cancel wire draw |
| Mouse wheel | Zoom in/out |
| Middle-click drag | Pan canvas |

---

## Troubleshooting

**Backend not reachable**: Check that `python main.py` is running in `app/backend/` and that port `48888` is not blocked by a firewall. Check the terminal for startup errors (e.g., missing `kohakunode` package — run `pip install -e .` from the project root).

**Frontend can't connect**: The Vite proxy requires the backend to be on port `48888`. If you changed the backend port, update the `proxy` in `app/frontend/vite.config.js`.

**"Function '...' is not registered"**: The KIR program references a function not in the backend registry. Register it via `POST /api/nodes/register` or add it to `builtin_nodes.py`.

**Node code fails to register**: The `code` field must define exactly one function named `node_func`. Python syntax errors in the code will be returned as a `400` error with the exception message in `detail`.

**"Control-flow construct ... is not allowed in dataflow mode"**: You have a `branch`, `switch`, `jump`, `parallel`, or namespace inside a `@mode dataflow` file. Either remove the control flow constructs, or switch to using scoped `@dataflow:` blocks in a non-dataflow-mode file instead.
