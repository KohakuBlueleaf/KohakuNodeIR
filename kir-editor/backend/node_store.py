"""Persistent storage for user-defined node type definitions.

Each node definition is saved as a JSON file on disk so it survives server
restarts.  On startup the store can re-register every saved definition into the
global Registry.

The default *store_dir* is resolved relative to **this file's location** so
that ``uvicorn main:app`` launched from any working directory always finds the
same storage folder.
"""

import json
import pathlib
from typing import Any

from kohakunode.engine.registry import Registry

# Directory that holds this source file — used for default store resolution.
_HERE = pathlib.Path(__file__).parent


class NodeStore:
    """Manage user-defined node definitions as JSON files on disk."""

    def __init__(self, store_dir: str | pathlib.Path = _HERE / "node_defs") -> None:
        self._dir = pathlib.Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_definition(self, definition: dict[str, Any]) -> None:
        """Save a node definition to ``{store_dir}/{type}.json``."""
        file_path = self._dir / f"{definition['type']}.json"
        file_path.write_text(json.dumps(definition, indent=2), encoding="utf-8")

    def load_all(self) -> list[dict[str, Any]]:
        """Load every ``.json`` file in the store directory."""
        definitions: list[dict[str, Any]] = []
        for path in sorted(self._dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            definitions.append(data)
        return definitions

    def delete_definition(self, type_name: str) -> None:
        """Delete the JSON file for *type_name*. Raises if it does not exist."""
        file_path = self._dir / f"{type_name}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"No stored definition for '{type_name}'")
        file_path.unlink()

    # ------------------------------------------------------------------
    # Registry integration
    # ------------------------------------------------------------------

    def register_all(self, registry: Registry) -> None:
        """Load all saved definitions and register them in *registry*.

        Each definition's ``code`` field is compiled via ``exec()`` and the
        resulting function is registered.
        """
        for definition in self.load_all():
            _register_from_definition(registry, definition)


def _register_from_definition(registry: Registry, definition: dict[str, Any]) -> None:
    """Compile a definition's ``code`` string and register the function.

    If the definition contains a ``properties`` list, each property's default
    value is made available as a keyword argument to the wrapped function.
    """
    code = definition["code"]
    type_name = definition["type"]
    output_names = [o["name"] for o in definition.get("outputs", [])]

    namespace: dict[str, Any] = {}
    exec(compile(code, f"<user-node:{type_name}>", "exec"), namespace)  # noqa: S102

    # The code must define exactly one callable named ``node_func``.
    if "node_func" not in namespace:
        raise ValueError(
            f"User code for '{type_name}' must define a function named 'node_func'"
        )

    fn = namespace["node_func"]

    # If the definition includes property defaults, wrap the function so that
    # the defaults are automatically applied as keyword arguments.
    properties = definition.get("properties", [])
    if properties:
        prop_defaults = {p["name"]: p.get("default") for p in properties if "name" in p}

        original_fn = fn
        def wrapped_fn(*args, **kwargs):
            merged = {**prop_defaults, **kwargs}
            return original_fn(*args, **merged)
        fn = wrapped_fn

    registry.register(type_name, fn, output_names=output_names)
