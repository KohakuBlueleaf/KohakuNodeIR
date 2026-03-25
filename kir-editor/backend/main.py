"""FastAPI backend for KohakuNodeIR visual programming system.

Endpoints
---------
REST:
    POST   /api/nodes/register        -- register a user-defined node type
    GET    /api/nodes                  -- list all registered node types
    DELETE /api/nodes/{type_name}      -- unregister a node type
    POST   /api/execute                -- parse and execute a KIR source string
    POST   /api/execute/kirgraph       -- compile .kirgraph L1→L3 and execute
    POST   /api/compile                -- compile .kirgraph to KIR text (L2 or L3)
    POST   /api/decompile              -- convert KIR text back to .kirgraph

WebSocket:
    WS     /api/ws/execute            -- execute KIR with streaming progress events
    WS     /api/ws/execute/kirgraph   -- execute .kirgraph with streaming events
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.compiler.strip_meta import StripMetaPass
from kohakunode.engine.registry import Registry
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.decompiler import KirGraphDecompiler
from kohakunode.kirgraph.schema import KirGraph
from kohakunode.parser.parser import parse
from kohakunode.serializer.writer import Writer

# ---------------------------------------------------------------------------
# Ensure the backend package directory is on sys.path so that the sibling
# modules (builtin_nodes, execution, node_store) are importable regardless of
# the working directory from which uvicorn is launched.
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent.resolve()
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from builtin_nodes import BUILTIN_NAMES, register_builtins  # noqa: E402
from execution import ExecutionSession  # noqa: E402
from node_store import NodeStore, _register_from_definition  # noqa: E402

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

registry = Registry()
node_store = NodeStore()  # defaults to <backend_dir>/node_defs

# Register built-in nodes, then restore any user-defined nodes from disk.
register_builtins(registry)
node_store.register_all(registry)

# Shared compiler / serialiser instances (stateless — safe to reuse).
_kgraph_compiler = KirGraphCompiler()
_dataflow_compiler = DataflowCompiler()
_strip_meta_pass = StripMetaPass()
_writer = Writer()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KohakuNodeIR Server",
    version="0.2.0",
    description="Backend for the KohakuNodeIR visual programming system.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class NodeIOField(BaseModel):
    name: str
    type: str = "any"


class NodePropertyField(BaseModel):
    name: str
    widget: str = "string"
    default: Any = None
    options: dict[str, Any] = Field(default_factory=dict)


class RegisterNodeRequest(BaseModel):
    name: str
    type: str
    category: str = "custom"
    description: str = ""
    inputs: list[NodeIOField] = Field(default_factory=list)
    outputs: list[NodeIOField] = Field(default_factory=list)
    properties: list[NodePropertyField] = Field(default_factory=list)
    code: str


class ExecuteRequest(BaseModel):
    kir_source: str


class ExecuteKirGraphRequest(BaseModel):
    kirgraph: dict[str, Any]


class CompileRequest(BaseModel):
    kirgraph: dict[str, Any]
    level: int = 3  # 2 = L2 (with @meta), 3 = L3 (stripped)


class DecompileRequest(BaseModel):
    kir_source: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile_kirgraph_to_kir(kirgraph_dict: dict[str, Any], level: int) -> str:
    """Compile a .kirgraph dict to KIR text at the requested level.

    Level 2 — KirGraphCompiler output + DataflowCompiler (retains @meta).
    Level 3 — Level 2 + StripMetaPass (pure execution IR).
    """
    if level not in (2, 3):
        raise ValueError(f"level must be 2 or 3, got {level}")

    graph = KirGraph.from_dict(kirgraph_dict)
    program = _kgraph_compiler.compile(graph)         # L1 → L2
    program = _dataflow_compiler.transform(program)   # sort dataflow blocks

    if level == 3:
        program = _strip_meta_pass.transform(program)  # L2 → L3

    return _writer.write(program)


# ---------------------------------------------------------------------------
# REST endpoints — node management
# ---------------------------------------------------------------------------


@app.post("/api/nodes/register")
async def register_node(req: RegisterNodeRequest) -> dict[str, Any]:
    """Dynamically create a node from user-supplied code and register it."""
    definition = req.model_dump()

    # If already registered, unregister first so we can update.
    if registry.has(req.type):
        if req.type in BUILTIN_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot overwrite built-in node '{req.type}'",
            )
        registry.unregister(req.type)

    try:
        _register_from_definition(registry, definition)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Persist to disk.
    node_store.save_definition(definition)

    return {"success": True, "type": req.type}


@app.get("/api/nodes")
async def list_nodes() -> list[dict[str, Any]]:
    """Return metadata for every registered node type."""
    nodes: list[dict[str, Any]] = []

    # Collect stored user definitions keyed by type for metadata lookup.
    user_defs: dict[str, dict[str, Any]] = {}
    for defn in node_store.load_all():
        user_defs[defn["type"]] = defn

    for name in registry.list_functions():
        spec = registry.lookup(name)
        is_builtin = name in BUILTIN_NAMES

        if name in user_defs:
            defn = user_defs[name]
            nodes.append(
                {
                    "name": defn.get("name", name),
                    "type": name,
                    "category": defn.get("category", "custom"),
                    "description": defn.get("description", ""),
                    "inputs": defn.get("inputs", []),
                    "outputs": defn.get("outputs", []),
                    "properties": defn.get("properties", []),
                    "builtin": False,
                }
            )
        else:
            nodes.append(
                {
                    "name": name,
                    "type": name,
                    "category": "builtin",
                    "description": "",
                    "inputs": [
                        {"name": n, "type": "any"} for n in spec.input_names
                    ],
                    "outputs": [
                        {"name": n, "type": "any"} for n in spec.output_names
                    ],
                    "builtin": is_builtin,
                }
            )

    return nodes


@app.delete("/api/nodes/{type_name}")
async def delete_node(type_name: str) -> dict[str, Any]:
    """Unregister a node type and remove its persisted definition."""
    if type_name in BUILTIN_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete built-in node '{type_name}'",
        )

    if not registry.has(type_name):
        raise HTTPException(
            status_code=404,
            detail=f"Node type '{type_name}' is not registered",
        )

    registry.unregister(type_name)

    try:
        node_store.delete_definition(type_name)
    except FileNotFoundError:
        pass  # Not persisted — that is fine.

    return {"success": True, "type": type_name}


# ---------------------------------------------------------------------------
# REST endpoints — execution
# ---------------------------------------------------------------------------


@app.post("/api/execute")
async def execute_kir(req: ExecuteRequest) -> dict[str, Any]:
    """Parse a KIR source string, execute it, and return results."""
    session = ExecutionSession(registry)
    result = session.execute(req.kir_source)
    return result


@app.post("/api/execute/kirgraph")
async def execute_kirgraph(req: ExecuteKirGraphRequest) -> dict[str, Any]:
    """Compile a .kirgraph (L1) to L3 KIR, execute it, and return results.

    Pipeline: KirGraphCompiler (L1→L2) → DataflowCompiler → StripMetaPass (L2→L3)
    → ExecutionSession.
    """
    try:
        kir_source = _compile_kirgraph_to_kir(req.kirgraph, level=3)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Compilation error: {exc}") from exc

    session = ExecutionSession(registry)
    result = session.execute(kir_source)
    # Include the compiled KIR in the response so the frontend can inspect it.
    result["kir_source"] = kir_source
    return result


# ---------------------------------------------------------------------------
# REST endpoints — compile / decompile
# ---------------------------------------------------------------------------


@app.post("/api/compile")
async def compile_kirgraph(req: CompileRequest) -> dict[str, Any]:
    """Compile a .kirgraph to KIR text without executing.

    ``level=2`` retains ``@meta`` annotations (useful for round-tripping).
    ``level=3`` strips metadata (pure executable IR).
    """
    try:
        kir_text = _compile_kirgraph_to_kir(req.kirgraph, level=req.level)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Compilation error: {exc}") from exc

    return {"kir_text": kir_text, "level": req.level}


@app.post("/api/decompile")
async def decompile_kir(req: DecompileRequest) -> dict[str, Any]:
    """Convert KIR source text back to a .kirgraph JSON object.

    Parses the KIR text into an AST (Level 2 with @meta annotations is
    preferred for accurate round-tripping) and runs ``KirGraphDecompiler``.
    """
    try:
        program = parse(req.kir_source)
        graph = KirGraphDecompiler().decompile(program)
        kirgraph_dict = graph.to_dict()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Decompilation error: {exc}"
        ) from exc

    return {"kirgraph": kirgraph_dict}


# ---------------------------------------------------------------------------
# WebSocket endpoint — KIR source
# ---------------------------------------------------------------------------


@app.websocket("/api/ws/execute")
async def ws_execute(ws: WebSocket) -> None:
    """Execute KIR programs with streaming progress events."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = message.get("type")
            if msg_type != "execute":
                await ws.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )
                continue

            kir_source = message.get("kir_source", "")
            await _ws_run_kir(ws, kir_source)

    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# WebSocket endpoint — KirGraph
# ---------------------------------------------------------------------------


@app.websocket("/api/ws/execute/kirgraph")
async def ws_execute_kirgraph(ws: WebSocket) -> None:
    """Compile a .kirgraph and execute it with streaming progress events."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = message.get("type")
            if msg_type != "execute":
                await ws.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )
                continue

            kirgraph_dict = message.get("kirgraph")
            if not isinstance(kirgraph_dict, dict):
                await ws.send_json(
                    {"type": "error", "message": "Missing or invalid 'kirgraph' field"}
                )
                continue

            # Compile first, then stream execution.
            try:
                kir_source = _compile_kirgraph_to_kir(kirgraph_dict, level=3)
            except Exception as exc:
                await ws.send_json(
                    {"type": "error", "message": f"Compilation error: {exc}"}
                )
                continue

            await ws.send_json({"type": "compiled", "kir_source": kir_source})
            await _ws_run_kir(ws, kir_source)

    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Shared WebSocket execution helper
# ---------------------------------------------------------------------------


async def _ws_run_kir(ws: WebSocket, kir_source: str) -> None:
    """Run a KIR program and stream events over *ws*.

    Output events are forwarded to the WebSocket in real time via the
    ``ws_callback`` hook on ``ExecutionSession``.  Captured outputs are *also*
    replayed at the end so clients that connect late still receive all events.
    """
    await ws.send_json({"type": "started"})

    loop = asyncio.get_running_loop()

    # Collect pending ws messages so we can send them from the event loop.
    # The callback runs inside the executor thread; we schedule the send on
    # the event loop to avoid threading issues with the WebSocket.
    pending: list[dict[str, Any]] = []

    def ws_callback(msg: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(pending.append, msg)

    session = ExecutionSession(registry, ws_callback=ws_callback)

    # Run execution in a thread so we don't block the event loop.
    result = await loop.run_in_executor(None, session.execute, kir_source)

    # Drain any pending messages accumulated during execution.
    for msg in pending:
        await ws.send_json(msg)

    if result["success"]:
        for var_name, var_value in result.get("variables", {}).items():
            await ws.send_json(
                {"type": "variable", "name": var_name, "value": var_value}
            )
        await ws.send_json(
            {"type": "completed", "variables": result.get("variables", {})}
        )
    else:
        await ws.send_json({"type": "error", "message": result.get("error", "")})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=48888)
