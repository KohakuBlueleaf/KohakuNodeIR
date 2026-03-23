"""FastAPI backend for KohakuNodeIR visual programming system.

Endpoints
---------
REST:
    POST   /api/nodes/register  -- register a user-defined node type
    GET    /api/nodes            -- list all registered node types
    DELETE /api/nodes/{type_name} -- unregister a node type
    POST   /api/execute          -- parse and execute a KIR program

WebSocket:
    WS     /api/ws/execute       -- execute with streaming progress events
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from kohakunode.engine.registry import Registry

from builtin_nodes import BUILTIN_NAMES, register_builtins
from execution import ExecutionSession
from node_store import NodeStore, _register_from_definition

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

registry = Registry()
node_store = NodeStore(store_dir="./node_defs")

# Register built-in nodes, then restore any user-defined nodes from disk.
register_builtins(registry)
node_store.register_all(registry)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KohakuNodeIR Server",
    version="0.1.0",
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


class RegisterNodeRequest(BaseModel):
    name: str
    type: str
    category: str = "custom"
    description: str = ""
    inputs: list[NodeIOField] = Field(default_factory=list)
    outputs: list[NodeIOField] = Field(default_factory=list)
    code: str


class ExecuteRequest(BaseModel):
    kir_source: str


# ---------------------------------------------------------------------------
# REST endpoints
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


@app.post("/api/execute")
async def execute_kir(req: ExecuteRequest) -> dict[str, Any]:
    """Parse a KIR source string, execute it, and return results."""
    session = ExecutionSession(registry)
    result = session.execute(req.kir_source)
    return result


# ---------------------------------------------------------------------------
# WebSocket endpoint
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
            await _ws_run_program(ws, kir_source)

    except WebSocketDisconnect:
        pass


async def _ws_run_program(ws: WebSocket, kir_source: str) -> None:
    """Run a KIR program and stream events over *ws*."""
    await ws.send_json({"type": "started"})

    session = ExecutionSession(registry)

    # Run execution in a thread so we don't block the event loop.
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, session.execute, kir_source)

    # Replay captured outputs as individual events.
    for output_msg in result.get("output", []):
        await ws.send_json(output_msg)

    if result["success"]:
        # Send variable updates.
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
