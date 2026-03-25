# kir-editor backend

FastAPI execution server for the KIR visual editor. Handles program execution,
compilation, and custom node type management.

## Endpoints

### REST

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/execute` | Parse and execute a KIR source string |
| `POST` | `/api/execute/kirgraph` | Compile KirGraph (L1 -> L3) and execute |
| `POST` | `/api/compile` | Compile KirGraph to KIR text (level 2 or 3) |
| `POST` | `/api/decompile` | Convert KIR text back to KirGraph JSON |
| `POST` | `/api/nodes/register` | Register a user-defined node type |
| `GET` | `/api/nodes` | List all registered node types |
| `DELETE` | `/api/nodes/{type_name}` | Unregister a node type |

### WebSocket

| Path | Description |
|---|---|
| `/api/ws/execute` | Execute KIR with streaming progress events |
| `/api/ws/execute/kirgraph` | Compile and execute KirGraph with streaming events |

WebSocket connections receive real-time `output`, `display`, `variable`, and
`completed`/`error` events during execution.

## Modules

| File | Description |
|---|---|
| `main.py` | FastAPI app, routes, compilation helpers |
| `execution.py` | `ExecutionSession` -- runs KIR programs with output capture |
| `builtin_nodes.py` | Standard library nodes (math, string, I/O, conversion) |
| `node_store.py` | `NodeStore` -- persists user-defined node definitions as JSON on disk |
| `requirements.txt` | Python dependencies |

## Custom node registration

Register nodes via `POST /api/nodes/register` with a JSON body containing
`name`, `type`, `inputs`, `outputs`, and `code`. The `code` field must define
a function named `node_func`. Definitions are persisted to `node_defs/` and
survive server restarts.

Built-in nodes (math, string, I/O, conversion) cannot be overwritten or deleted.

## Running

```bash
pip install -r requirements.txt
python main.py                    # starts on 0.0.0.0:48888
# or:
uvicorn main:app --host 0.0.0.0 --port 48888 --reload
```

Requires the `kohakunode` Python package (`pip install -e .` from repo root).
