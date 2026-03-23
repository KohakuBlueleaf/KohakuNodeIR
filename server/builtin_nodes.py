"""Register the standard library of built-in node types.

These are always available and cannot be deleted via the REST API.
"""

from __future__ import annotations

from kohakunode.engine.registry import Registry

# Keep a set of built-in names so the server can distinguish user-defined nodes
# from built-in ones and prevent deletion of built-ins.
BUILTIN_NAMES: set[str] = set()


def register_builtins(registry: Registry) -> None:
    """Populate *registry* with the default set of node types."""

    def _reg(name: str, func, **kwargs) -> None:  # noqa: ANN001
        registry.register(name, func, **kwargs)
        BUILTIN_NAMES.add(name)

    # ── Math ──────────────────────────────────────────────────────────
    _reg("add", lambda a, b: a + b, output_names=["result"])
    _reg("subtract", lambda a, b: a - b, output_names=["result"])
    _reg("multiply", lambda a, b: a * b, output_names=["result"])
    _reg("divide", lambda a, b: a / b if b != 0 else 0, output_names=["result"])

    # ── Comparison ────────────────────────────────────────────────────
    _reg("greater_than", lambda a, b: a > b, output_names=["result"])
    _reg("less_than", lambda a, b: a < b, output_names=["result"])
    _reg("equal", lambda a, b: a == b, output_names=["result"])
    _reg("and_node", lambda a, b: bool(a) and bool(b), output_names=["result"])
    _reg("not_node", lambda value: not bool(value), output_names=["result"])

    # ── String ────────────────────────────────────────────────────────
    _reg("concat", lambda a, b: str(a) + str(b), output_names=["result"])
    _reg(
        "format_string",
        lambda template, value: str(template).format(value),
        output_names=["result"],
    )

    # ── File I/O ──────────────────────────────────────────────────────
    _reg(
        "read_file",
        lambda path: open(path, encoding="utf-8").read(),  # noqa: SIM115
        output_names=["data"],
    )
    _reg(
        "write_file",
        lambda path, data: open(path, "w", encoding="utf-8").write(str(data)),  # noqa: SIM115
        output_names=[],
    )

    # ── Convert ───────────────────────────────────────────────────────
    _reg("to_int", lambda value: int(value), output_names=["result"])
    _reg("to_float", lambda value: float(value), output_names=["result"])
    _reg("to_string", lambda value: str(value), output_names=["result"])
