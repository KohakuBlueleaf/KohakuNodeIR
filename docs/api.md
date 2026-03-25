# KohakuNodeIR -- API Reference

This document covers the **kohakunode Python library API** (primary), the **kohakunode-rs Rust crate API**, and the **KIR Editor REST/WebSocket endpoints** (development tool).

---

## Python API (kohakunode)

The `kohakunode` package is the reference implementation of KIR. Install it with `uv pip install -e .` from the project root.

### Parsing

#### `parse(source: str) -> Program`

Parse a KIR source string and return the root `Program` AST node.

```python
from kohakunode import parse

program = parse("x = 10\n(x, 2)multiply(result)")
print(program.body)  # list of Statement nodes
```

Raises `KirSyntaxError` if the source contains invalid syntax.

#### `parse_file(path: str | Path) -> Program`

Read a `.kir` file and parse it. Convenience wrapper around `parse()`.

```python
from kohakunode import parse_file

program = parse_file("examples/kir_basics/hello_world.kir")
```

### Execution

#### `run(source, registry=None, validate=True) -> VariableStore`

One-shot: parse and execute a KIR source string.

```python
from kohakunode import run, Registry

registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])

store = run("(3, 4)add(sum)", registry=registry)
print(store.get("sum"))  # 7
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | required | KIR source string |
| `registry` | `Registry \| None` | `None` | Pre-populated function registry. A fresh empty one is created when `None`. |
| `validate` | `bool` | `True` | Run semantic validation before compilation |

**Returns:** `VariableStore` -- the interpreter's variable store after execution.

#### `run_file(path, registry=None, validate=True) -> VariableStore`

One-shot: read a `.kir` file, parse it, and execute it. Same parameters as `run()` except `path` replaces `source`.

#### `Executor(registry=None, validate=True)`

Class that holds shared state across multiple runs. Use when you want to reuse the same registry for multiple programs.

```python
from kohakunode import Executor

executor = Executor()
executor.register("square", lambda x: x * x, output_names=["result"])

store = executor.execute_source("(5)square(y)")
print(store.get("y"))  # 25
```

**Methods:**

| Method | Description |
|--------|-------------|
| `execute(program: Program) -> VariableStore` | Execute a parsed AST |
| `execute_source(source: str) -> VariableStore` | Parse and execute a source string |
| `execute_file(path) -> VariableStore` | Read, parse, and execute a file |
| `register(name, func, **kwargs) -> Executor` | Register a function (returns self for chaining) |
| `register_decorator(**kwargs)` | Returns a decorator that registers the decorated function |

### Registry

#### `Registry()`

Maps function names to `FunctionSpec` objects. Input names and defaults are inferred from the function signature when not provided explicitly.

```python
from kohakunode import Registry

registry = Registry()

# Basic registration
registry.register("add", lambda a, b: a + b, output_names=["result"])

# With explicit input names and defaults
registry.register("scale", lambda x, factor: x * factor,
                   input_names=["x", "factor"],
                   output_names=["result"],
                   defaults={"factor": 1.0})

# Decorator style
@registry.register_decorator(output_names=["result"])
def multiply(a, b):
    return a * b
```

**Methods:**

| Method | Description |
|--------|-------------|
| `register(name, func, input_names=None, output_names=None, defaults=None) -> FunctionSpec` | Register a callable |
| `register_decorator(name=None, output_names=None)` | Returns a decorator for registration |
| `lookup(name) -> FunctionSpec` | Look up a function (raises `KirRuntimeError` if not found) |
| `has(name) -> bool` | Check if a function is registered |
| `unregister(name)` | Remove a registered function |
| `list_functions() -> list[str]` | List all registered function names (sorted) |
| `clear()` | Remove all registered functions |

#### `FunctionSpec`

Dataclass holding a registered function's metadata:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Function name as used in KIR |
| `func` | `Callable` | The Python callable |
| `input_names` | `list[str]` | Parameter names |
| `output_names` | `list[str]` | Output variable names |
| `defaults` | `dict[str, Any]` | Default values for parameters |

### Validation

#### `validate(program: Program) -> ValidationResult`

Run all analyzers and return results. Never raises -- issues are collected into errors and warnings.

#### `validate_or_raise(program: Program) -> ValidationResult`

Same as `validate()`, but raises `KirAnalysisError` if any errors are found. Warnings are still returned in the result.

`ValidationResult` fields: `errors`, `warnings`, `is_valid`, `all_issues`.

### Compiler Passes

#### `DataflowCompiler().transform(program: Program) -> Program`

Expand `@dataflow:` blocks by topologically sorting their statements and inlining them into the parent body. Also handles `@mode dataflow` (whole-file dataflow). This is the L2 -> L3 compilation step.

#### `StripMetaPass().transform(program: Program) -> Program`

Remove all `@meta` annotations from the AST. Optional -- use when you don't need round-tripping metadata.

### Serializer

#### `Writer().write(program: Program) -> str`

Serialize a `Program` AST back to KIR source text.

```python
from kohakunode import parse, Writer

program = parse("x = 10\n(x, 2)add(result)")
text = Writer().write(program)
print(text)  # x = 10\n(x, 2)add(result)\n
```

#### `read(path) -> Program`

Read a `.kir` file and return a `Program` AST. Wraps file I/O with `KirSyntaxError` on failure.

#### `read_string(source: str) -> Program`

Parse a KIR source string. Convenience alias for `parse()` available from the serializer module.

### KirGraph (L1 IR)

#### `KirGraph`

Dataclass representing the Level 1 graph topology.

```python
from kohakunode import KirGraph

# Load from JSON
graph = KirGraph.from_json(open("my_graph.kirgraph").read())

# Serialize to JSON
json_str = graph.to_json()

# Access nodes and edges
for node in graph.nodes:      # list[KGNode]
    print(node.id, node.type)
for edge in graph.edges:      # list[KGEdge]
    print(edge.from_node, "->", edge.to_node)
```

**Methods:** `from_json(text)`, `to_json()`, `from_dict(d)`, `to_dict()`.

#### `KirGraphCompiler().compile(graph: KirGraph) -> Program`

Compile a KirGraph (L1) to a Program AST (L2). Determines execution order, generates variable names, and emits `@meta` annotations.

#### `KirGraphDecompiler().decompile(program: Program) -> KirGraph`

Reconstruct a KirGraph (L1) from a Program AST (L2). Requires `@meta node_id=...` annotations for accurate round-tripping.

### Layout

#### `kir_to_graph(source: str) -> KirGraph`

Parse KIR source and extract a `KirGraph` by walking the AST, tracking variable definitions and usages to wire data edges. Synthesizes merge nodes where needed.

```python
from kohakunode.layout.ascii_view import kir_to_graph

graph = kir_to_graph(open("program.kir").read())
```

#### `auto_layout(graph: KirGraph) -> KirGraph`

Assign node positions using Fischer-style BFS layout. Returns a new `KirGraph` with updated `meta.pos` and `meta.size` fields.

```python
from kohakunode.layout.auto_layout import auto_layout

positioned = auto_layout(graph)
```

### Full Pipeline Example

```python
from kohakunode import (
    parse, DataflowCompiler, StripMetaPass,
    Executor, Registry, KirGraphCompiler, KirGraph, Writer
)

# Load a .kirgraph and compile to L2 KIR
graph = KirGraph.from_json(open("graph.kirgraph").read())
program = KirGraphCompiler().compile(graph)

# Write L2 to text
l2_text = Writer().write(program)

# Compile to L3 (expand @dataflow:, strip @meta)
program = DataflowCompiler().transform(program)
program = StripMetaPass().transform(program)

# Execute
registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])
executor = Executor(registry=registry)
store = executor.execute(program)
```

### Error Types

| Exception | When raised |
|-----------|-------------|
| `KirError` | Base class for all KohakuNodeIR errors |
| `KirSyntaxError` | Parser encounters invalid syntax. Has `line`, `column`, `source_line` attributes. |
| `KirAnalysisError` | Validator finds semantic errors. Has `line`, `node_context` attributes. |
| `KirCompilationError` | Dataflow compiler finds issues (e.g., control flow in dataflow mode) |
| `KirRuntimeError` | Interpreter error (undefined function, etc.). Has `line`, `function_name` attributes. |

---

## Rust API (kohakunode-rs)

The Rust crate `kohakunode-rs` provides the same core pipeline as a PyO3 native module or as WASM. All functions use a **JSON bridge** -- they accept and return JSON strings rather than exposing full Rust types to Python/JS.

### PyO3 Functions

Available via `import kohakunode_rs` after building with maturin.

| Function | Input | Output | Description |
|----------|-------|--------|-------------|
| `parse_kir(text)` | KIR source `str` | Program AST JSON `str` | Parse KIR to AST |
| `compile_dataflow(program_json)` | Program JSON `str` | Program JSON `str` | Expand `@dataflow:` blocks |
| `strip_meta(program_json)` | Program JSON `str` | Program JSON `str` | Remove `@meta` annotations |
| `compile_kirgraph(kirgraph_json)` | KirGraph JSON `str` | Program JSON `str` | L1 -> L2 compilation |

The `layout` and `serializer` PyO3 bindings are defined but not yet registered in the root module. The following functions exist in the Rust source and are available via WASM:

| Function | Input | Output | Description |
|----------|-------|--------|-------------|
| `kir_to_graph(source)` | KIR source | KirGraph JSON | Extract graph from `.kir` |
| `auto_layout(graph_json)` | KirGraph JSON | KirGraph JSON | Assign node positions |
| `score_layout(graph_json)` | KirGraph JSON | `f64` | Layout quality score |
| `optimize_layout(graph_json, n)` | KirGraph JSON + iterations | KirGraph JSON | Improve layout |
| `write_kir(program_json)` | Program JSON | KIR text | Serialize AST to KIR |
| `decompile(program_json)` | Program JSON | KirGraph JSON | L2 -> L1 decompilation |

### WASM Exports

The WASM module exports all of the above functions. They are used by the KIR Editor frontend for in-browser parsing, compilation, and layout. See the WASM exports table in [architecture.md](architecture.md) for the complete list.

```javascript
import init, { parse_kir, compile_kirgraph, write_kir } from './wasm/kohakunode_rs.js';

await init();
const ast_json = parse_kir("x = 10\n(x, 2)add(result)");
```

---

## KIR Editor API (Development Tool)

The KIR Editor backend (`kir-editor/backend/`) is a FastAPI application that wraps the `kohakunode` Python engine. These endpoints are for the editor UI, not for general library use.

**Base URL**: `http://localhost:48888`

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/nodes/register` | Register a user-defined node type |
| `GET` | `/api/nodes` | List all registered node types |
| `DELETE` | `/api/nodes/{type_name}` | Unregister a user-defined node type |
| `POST` | `/api/execute` | Execute a KIR source string synchronously |
| `POST` | `/api/execute/kirgraph` | Compile `.kirgraph` to L3 and execute |
| `POST` | `/api/compile` | Compile `.kirgraph` to KIR text (L2 or L3) |
| `POST` | `/api/decompile` | Convert KIR L2 text back to `.kirgraph` |

### WebSocket Endpoints

| Path | Description |
|------|-------------|
| `WS /api/ws/execute` | Execute KIR with streaming progress events |
| `WS /api/ws/execute/kirgraph` | Compile `.kirgraph` and execute with streaming |

### POST /api/execute

**Request:**

```json
{ "kir_source": "x = 10\ny = 20\n(x, y)add(sum)\n(sum)print()" }
```

**Response (200):**

```json
{
  "success": true,
  "variables": { "x": 10, "y": 20, "sum": 30 },
  "output": [{ "type": "output", "value": "30" }]
}
```

HTTP status is always 200. The `success` field indicates whether execution succeeded. On failure, an `error` field contains the error message.

### POST /api/compile

**Request:**

```json
{
  "kirgraph": { "version": "0.1.0", "nodes": [...], "edges": [...] },
  "level": 3
}
```

`level` is `2` (L2 with `@meta`) or `3` (L3 pure sequential, default).

**Response:** `{ "kir_text": "...", "level": 3 }`

### POST /api/nodes/register

Register a custom node type. The `code` field must define a Python function named `node_func`.

```json
{
  "name": "Square", "type": "square", "category": "math",
  "inputs": [{ "name": "value", "type": "float" }],
  "outputs": [{ "name": "result", "type": "float" }],
  "code": "def node_func(value):\n    return value * value"
}
```

Properties can define typed widgets (`string`, `number`, `boolean`, `select`, `slider`) with options.

### WebSocket Event Protocol

```
Client                              Server
  |-- {"type":"execute","kir_source":...} -->|
  |<-- {"type":"started"} ------------------|
  |<-- {"type":"output","value":"..."} ------ (0..N)
  |<-- {"type":"variable","name":"...","value":...} (0..N)
  |<-- {"type":"completed","variables":{...}} |
```

On error, a `{"type":"error","message":"..."}` is sent instead of `completed`.

The `/api/ws/execute/kirgraph` endpoint adds a `{"type":"compiled","kir_source":"..."}` event before `started`.

### Built-in Node Types

The following are always registered and cannot be deleted:

| Category | Types |
|----------|-------|
| Math | `add`, `subtract`, `multiply`, `divide` |
| Comparison | `greater_than`, `less_than`, `equal`, `and_node`, `not_node` |
| String | `concat`, `format_string` |
| File I/O | `read_file`, `write_file` |
| Conversion | `to_int`, `to_float`, `to_string` |
| Utility | `identity`, `store`, `load`, `print`, `display` |
