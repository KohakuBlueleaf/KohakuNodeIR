"""Data classes for the .kirgraph (Level 1 IR) format.

A .kirgraph file is a JSON object containing a flat list of nodes and edges
that directly represents the visual node graph topology.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class KGPort:
    """A data port on a node (input or output)."""

    port: str
    type: str = "any"
    default: Any = None  # only meaningful for inputs

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"port": self.port, "type": self.type}
        if self.default is not None:
            d["default"] = self.default
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KGPort:
        return cls(
            port=d["port"],
            type=d.get("type", "any"),
            default=d.get("default"),
        )


@dataclass
class KGEdge:
    """An edge connecting two ports across two nodes."""

    type: str  # "data" or "control"
    from_node: str
    from_port: str
    to_node: str
    to_port: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "from": {"node": self.from_node, "port": self.from_port},
            "to": {"node": self.to_node, "port": self.to_port},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KGEdge:
        return cls(
            type=d["type"],
            from_node=d["from"]["node"],
            from_port=d["from"]["port"],
            to_node=d["to"]["node"],
            to_port=d["to"]["port"],
        )


@dataclass
class KGNode:
    """A node in the .kirgraph."""

    id: str
    type: str
    name: str
    data_inputs: list[KGPort] = field(default_factory=list)
    data_outputs: list[KGPort] = field(default_factory=list)
    ctrl_inputs: list[str] = field(default_factory=list)
    ctrl_outputs: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "data_inputs": [p.to_dict() for p in self.data_inputs],
            "data_outputs": [p.to_dict() for p in self.data_outputs],
            "ctrl_inputs": list(self.ctrl_inputs),
            "ctrl_outputs": list(self.ctrl_outputs),
        }
        if self.properties:
            d["properties"] = self.properties
        if self.meta:
            d["meta"] = self.meta
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KGNode:
        return cls(
            id=d["id"],
            type=d["type"],
            name=d["name"],
            data_inputs=[KGPort.from_dict(p) for p in d.get("data_inputs", [])],
            data_outputs=[KGPort.from_dict(p) for p in d.get("data_outputs", [])],
            ctrl_inputs=d.get("ctrl_inputs", []),
            ctrl_outputs=d.get("ctrl_outputs", []),
            properties=d.get("properties", {}),
            meta=d.get("meta", {}),
        )


@dataclass
class KirGraph:
    """Root object of a .kirgraph file."""

    version: str = "0.1.0"
    nodes: list[KGNode] = field(default_factory=list)
    edges: list[KGEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KirGraph:
        return cls(
            version=d.get("version", "0.1.0"),
            nodes=[KGNode.from_dict(n) for n in d.get("nodes", [])],
            edges=[KGEdge.from_dict(e) for e in d.get("edges", [])],
        )

    def to_json(self, **kwargs: Any) -> str:
        """Serialize to a JSON string."""
        defaults = {"indent": 2, "ensure_ascii": False}
        defaults.update(kwargs)
        return json.dumps(self.to_dict(), **defaults)

    @classmethod
    def from_json(cls, text: str) -> KirGraph:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(text))
