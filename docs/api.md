# KohakuNodeIR -- Backend API Reference

**Base URL**: `http://localhost:48888`

The KIR Editor backend (FastAPI) exposes REST endpoints for node management, KIR execution, and graph compilation/decompilation, plus WebSocket endpoints for streaming execution.

**REST endpoints:**
- `POST /api/nodes/register` -- register a user-defined node type
- `GET /api/nodes` -- list all registered node types
- `DELETE /api/nodes/{type_name}` -- unregister a node type
- `POST /api/execute` -- execute a KIR source string synchronously
- `POST /api/execute/kirgraph` -- compile `.kirgraph` to L3 and execute
- `POST /api/compile` -- compile `.kirgraph` to KIR text (L2 or L3)
- `POST /api/decompile` -- convert KIR text back to `.kirgraph`

**WebSocket endpoints:**
- `WS /api/ws/execute` -- execute KIR with streaming progress events
- `WS /api/ws/execute/kirgraph` -- compile `.kirgraph` and execute with streaming events

---

## REST Endpoints

### POST /api/nodes/register

Register a new user-defined node type, or update an existing one.

Built-in nodes (`add`, `subtract`, `multiply`, `divide`, `greater_than`, `less_than`, `equal`, `and_node`, `not_node`, `concat`, `format_string`, `read_file`, `write_file`, `store`, `load`, `identity`, `to_int`, `to_float`, `to_string`) cannot be overwritten.

**Request body**:

```json
{
  "name": "My Squarer",
  "type": "my_squarer",
  "category": "math",
  "description": "Squares a number.",
  "inputs": [
    { "name": "value", "type": "float" }
  ],
  "outputs": [
    { "name": "result", "type": "float" }
  ],
  "properties": [
    { "name": "exponent", "widget": "slider", "default": 2, "options": { "min": 1, "max": 10, "step": 1 } }
  ],
  "code": "def node_func(value, exponent=2):\n    return value ** exponent"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Human-readable display name |
| `type` | string | yes | Unique type key used in KIR function calls |
| `category` | string | no | UI category (default: `"custom"`) |
| `description` | string | no | Short description shown in palette |
| `inputs` | array | no | Input port definitions `[{name, type}]` |
| `outputs` | array | no | Output port definitions `[{name, type}]` |
| `properties` | array | no | Property schema definitions (see below) |
| `code` | string | yes | Python source; must define `node_func` |

The `code` field must contain a Python function named `node_func`. Its parameters must match the declared `inputs` by name. Return values must match the order of `outputs` (single value for one output, tuple for multiple). Property defaults are injected as keyword arguments.

```python
# Single output
def node_func(value):
    return value * value

# Multiple outputs
def node_func(a, b):
    return a + b, a - b

# With property defaults
def node_func(value, exponent=2):
    return value ** exponent
```

#### Property schema

Each property in the `properties` array defines a configurable parameter with a widget type:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Property name (used as keyword argument to `node_func`) |
| `widget` | string | Widget type: `"string"`, `"number"`, `"boolean"`, `"select"`, `"slider"` |
| `default` | any | Default value for the property |
| `options` | object | Widget-specific options (see table below) |

| Widget | Options |
|--------|---------|
| `string` | (none) |
| `number` | (none) |
| `boolean` | (none) |
| `select` | `{ "choices": "option1,option2,option3" }` |
| `slider` | `{ "min": 0, "max": 100, "step": 1 }` |

**Response** (200):

```json
{ "success": true, "type": "my_squarer" }
```

**Error** (400):

```json
{ "detail": "Cannot overwrite built-in node 'add'" }
```

```json
{ "detail": "User code for 'my_squarer' must define a function named 'node_func'" }
```

The definition is persisted to `kir-editor/backend/node_defs/{type}.json` and survives server restarts.

---

### GET /api/nodes

List all registered node types, including built-ins and user-defined nodes.

**Request**: No body.

**Response** (200):

```json
[
  {
    "name": "add",
    "type": "add",
    "category": "builtin",
    "description": "",
    "inputs": [
      { "name": "a", "type": "any" },
      { "name": "b", "type": "any" }
    ],
    "outputs": [
      { "name": "result", "type": "any" }
    ],
    "builtin": true
  },
  {
    "name": "My Squarer",
    "type": "my_squarer",
    "category": "math",
    "description": "Squares a number.",
    "inputs": [{ "name": "value", "type": "float" }],
    "outputs": [{ "name": "result", "type": "float" }],
    "builtin": false
  }
]
```

Each entry has the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name |
| `type` | string | Type key (used as function name in KIR) |
| `category` | string | `"builtin"` for built-ins, user-defined category otherwise |
| `description` | string | Short description |
| `inputs` | array | `[{name, type}]` |
| `outputs` | array | `[{name, type}]` |
| `builtin` | boolean | Whether this is a protected built-in |

The frontend's node palette fetches this endpoint on startup to populate the available node types.

---

### DELETE /api/nodes/{type_name}

Unregister a user-defined node type and delete its persisted definition.

Built-in nodes cannot be deleted.

**Path parameter**: `type_name` -- the type key to delete.

**Response** (200):

```json
{ "success": true, "type": "my_squarer" }
```

**Error** (400):

```json
{ "detail": "Cannot delete built-in node 'add'" }
```

**Error** (404):

```json
{ "detail": "Node type 'nonexistent' is not registered" }
```

---

### POST /api/execute

Parse and execute a KIR source string synchronously. Returns after execution completes.

**Request body**:

```json
{
  "kir_source": "x = 10\ny = 20\n(x, y)add(sum)\n(sum)print()"
}
```

**Response** (200, success):

```json
{
  "success": true,
  "variables": {
    "x": 10,
    "y": 20,
    "sum": 30
  },
  "output": [
    { "type": "output", "value": "30" }
  ]
}
```

**Response** (200, failure):

```json
{
  "success": false,
  "error": "Function 'unknown_func' is not registered",
  "output": []
}
```

Note: HTTP status is always 200. The `success` field in the body indicates whether execution succeeded. Partial output captured before the error is included in `output`.

**Response fields**:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether execution completed without error |
| `variables` | object | Final variable store snapshot (JSON-serializable values only; non-serializable values appear as their `repr()`) |
| `output` | array | Ordered list of output events from `print` and `display` calls |
| `error` | string | Error message (only present when `success` is false) |

**Output event object**:

```json
{ "type": "output", "value": "some string" }
```

The `display` built-in produces `repr()` of its argument. The `print` built-in produces `str()`.

---

### POST /api/execute/kirgraph

Compile a `.kirgraph` (L1) to L3 KIR and execute it in one step. Combines `KirGraphCompiler`, `DataflowCompiler`, `StripMetaPass`, and `ExecutionSession`.

**Request body**:

```json
{
  "kirgraph": {
    "version": "0.1.0",
    "nodes": [ ... ],
    "edges": [ ... ]
  }
}
```

**Response** (200, success):

```json
{
  "success": true,
  "variables": { "x": 10, "sum": 30 },
  "output": [{ "type": "output", "value": "30" }],
  "kir_source": "x = 10\n..."
}
```

The response includes a `kir_source` field containing the compiled L3 KIR text, so the frontend can inspect what was executed.

**Response** (400):

```json
{ "detail": "Compilation error: ..." }
```

---

### POST /api/compile

Compile a `.kirgraph` to KIR text without executing. Supports both L2 (with `@meta`) and L3 (stripped) output.

**Request body**:

```json
{
  "kirgraph": {
    "version": "0.1.0",
    "nodes": [ ... ],
    "edges": [ ... ]
  },
  "level": 3
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `kirgraph` | object | yes | A valid `.kirgraph` JSON object |
| `level` | int | no | `2` = L2 with `@meta` (default for round-tripping), `3` = L3 pure sequential (default: `3`) |

**Response** (200):

```json
{ "kir_text": "val_a_value = 10\n...", "level": 3 }
```

**Error** (400):

```json
{ "detail": "Compilation error: ..." }
```

**Error** (422):

```json
{ "detail": "level must be 2 or 3, got 1" }
```

---

### POST /api/decompile

Convert KIR L2 text (with `@meta` annotations) back to a `.kirgraph` JSON object. This is the L2 -> L1 direction of the pipeline.

**Request body**:

```json
{
  "kir_source": "@meta node_id=\"val_a\" pos=(100, 100)\nval_a_value = 10\n..."
}
```

L2 KIR with `@meta node_id=...` annotations is required for accurate round-tripping. L3 KIR (stripped of `@meta`) will still parse but will produce incomplete graph topology.

**Response** (200):

```json
{
  "kirgraph": {
    "version": "0.1.0",
    "nodes": [ ... ],
    "edges": [ ... ]
  }
}
```

**Error** (400):

```json
{ "detail": "Decompilation error: ..." }
```

---

## WebSocket Endpoints

### WS /api/ws/execute

Execute KIR programs with streaming progress. A single WebSocket connection can run multiple programs sequentially.

**Connection**: `ws://localhost:48888/api/ws/execute`

When the Vite dev server is running, use `ws://localhost:5174/api/ws/execute` (proxied).

### Client -> Server Messages

#### execute

Run a KIR program.

```json
{
  "type": "execute",
  "kir_source": "x = 10\n(x, 2)multiply(result)\n(result)print()"
}
```

Any message with an unknown `type` field receives an error response and is otherwise ignored.

### Server -> Client Messages

Messages are sent in the following order for a successful run:

#### started

Sent immediately after the `execute` message is received, before execution begins.

```json
{ "type": "started" }
```

#### output

One message per `print` or `display` call, in execution order.

```json
{ "type": "output", "value": "20" }
```

#### variable

One message per variable in the final store, sent after all output events.

```json
{ "type": "variable", "name": "result", "value": 20 }
```

#### completed

Sent after all variable messages. Includes the full variable snapshot for convenience.

```json
{
  "type": "completed",
  "variables": { "x": 10, "result": 20 }
}
```

#### error

Sent instead of `completed` when execution fails. May appear after some `output` messages if print was called before the error.

```json
{ "type": "error", "message": "Function 'foo' is not registered" }
```

Also sent for malformed JSON:

```json
{ "type": "error", "message": "Invalid JSON" }
```

### WebSocket Event Flow Diagram

```
Client                              Server
  |                                   |
  |-- {"type":"execute","kir_source"} -->|
  |                                   |
  |<-- {"type":"started"} ------------|
  |<-- {"type":"output","value":"..."} (0..N times)
  |<-- {"type":"variable","name":"...","value":...} (0..N times)
  |<-- {"type":"completed","variables":{...}} -----|
  |                                   |
  |  (connection stays open)          |
  |-- {"type":"execute",...} ---------->|
  |   (another program can be sent)   |
```

---

### WS /api/ws/execute/kirgraph

Compile a `.kirgraph` and execute it with streaming progress. Same event protocol as `WS /api/ws/execute`, with an additional `compiled` event.

**Connection**: `ws://localhost:48888/api/ws/execute/kirgraph`

### Client -> Server Messages

#### execute

```json
{
  "type": "execute",
  "kirgraph": {
    "version": "0.1.0",
    "nodes": [ ... ],
    "edges": [ ... ]
  }
}
```

### Server -> Client Messages

Same as `WS /api/ws/execute` with one additional message sent before `started`:

#### compiled

Sent after successful compilation, before execution begins.

```json
{ "type": "compiled", "kir_source": "val_a_value = 10\n..." }
```

After `compiled`, the server sends `started`, then the standard `output`, `variable`, and `completed` (or `error`) sequence.

On compilation failure:

```json
{ "type": "error", "message": "Compilation error: ..." }
```

---

## Built-in Node Types

The following node types are always registered and cannot be deleted or overwritten:

### Math

| Type | Inputs | Outputs | Description |
|------|--------|---------|-------------|
| `add` | `a`, `b` | `result` | `a + b` |
| `subtract` | `a`, `b` | `result` | `a - b` |
| `multiply` | `a`, `b` | `result` | `a * b` |
| `divide` | `a`, `b` | `result` | `a / b` (returns 0 if `b == 0`) |

### Comparison

| Type | Inputs | Outputs | Description |
|------|--------|---------|-------------|
| `greater_than` | `a`, `b` | `result` | `a > b` |
| `less_than` | `a`, `b` | `result` | `a < b` |
| `equal` | `a`, `b` | `result` | `a == b` |
| `and_node` | `a`, `b` | `result` | `bool(a) and bool(b)` |
| `not_node` | `value` | `result` | `not bool(value)` |

### String

| Type | Inputs | Outputs | Description |
|------|--------|---------|-------------|
| `concat` | `a`, `b` | `result` | `str(a) + str(b)` |
| `format_string` | `template`, `value` | `result` | `str(template).format(value)` |

### File I/O

| Type | Inputs | Outputs | Description |
|------|--------|---------|-------------|
| `read_file` | `path` | `data` | Read UTF-8 file, return string |
| `write_file` | `path`, `data` | (none) | Write `str(data)` to file |

### Type Conversion

| Type | Inputs | Outputs | Description |
|------|--------|---------|-------------|
| `to_int` | `value` | `result` | `int(value)` |
| `to_float` | `value` | `result` | `float(value)` |
| `to_string` | `value` | `result` | `str(value)` |

### Utility

| Type | Inputs | Outputs | Description |
|------|--------|---------|-------------|
| `identity` | `value` | `result` | Pass-through (returns input unchanged) |
| `store` | `value` | `value` | Identity (used in store/load pattern) |
| `load` | `value` | `value` | Identity (used in store/load pattern) |
| `print` | `value` | (none) | Print `str(value)` (output captured by server) |
| `display` | `value` | `pass` | Print `repr(value)`, pass value through |

---

## Python Engine API

The `kohakunode` package can also be used directly in Python, without the server.

### Quick execute

```python
from kohakunode import run, Registry

registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])

store = run("(3, 4)add(sum)", registry=registry)
print(store.get("sum"))  # 7
```

### Full pipeline

```python
from kohakunode import (
    parse, validate_or_raise, DataflowCompiler, StripMetaPass,
    Executor, Registry, KirGraphCompiler, KirGraph
)

# Load a .kirgraph and compile to L2 KIR
graph = KirGraph.from_json(open("graph.kirgraph").read())
compiler = KirGraphCompiler()
program = compiler.compile(graph)   # L2 Program AST

# Compile to L3 (expand @dataflow:, strip @meta)
program = DataflowCompiler().transform(program)
program = StripMetaPass().transform(program)

# Execute
registry = Registry()
# ... register functions ...
executor = Executor(registry=registry)
store = executor.execute(program)
```

### Decompile L2 back to L1

```python
from kohakunode import KirGraphDecompiler, parse

program = parse(open("compiled_l2.kir").read())
graph = KirGraphDecompiler().decompile(program)
print(graph.to_json())
```

### Error types

| Exception | When raised |
|-----------|-------------|
| `KirSyntaxError` | Parser encounters invalid syntax |
| `KirAnalysisError` | Validator finds semantic errors |
| `KirCompilationError` | Dataflow compiler finds control flow in dataflow mode |
| `KirRuntimeError` | Interpreter error (undefined function, etc.) |
| `KirError` | Base class for all above |

---

## Error Handling

All error responses from REST endpoints use standard HTTP status codes with a JSON body:

```json
{ "detail": "error message here" }
```

HTTP errors use:
- `400 Bad Request` -- invalid input (bad code, overwriting built-in, etc.)
- `404 Not Found` -- resource does not exist (unknown node type)

Execution errors (syntax errors, runtime errors in KIR) do not produce HTTP 4xx/5xx -- they return HTTP 200 with `"success": false` in the body, because the request itself was structurally valid.
