# Writing nodes

A node is a Python function registered in a `NodeLibrary`. Its parameters are
the node's inputs (types and defaults from the annotations), its outputs are
named with `outputs=`.

```python
from kohakunode import NodeLibrary

lib = NodeLibrary("gbc")


@lib.node(outputs=["node"])
def entity(crop: Image, box: Box, max_tokens: int = 256) -> Node:
    """Caption one crop."""
    ...


@lib.node(outputs=["seen", "is_new"])
def register(seen: list, box: dict) -> tuple:  # several outputs: return a tuple
    ...
```

## Rules a node must keep

Programs run in parallel by default, so a node may depend only on its inputs
and may affect the job only through its outputs. When an implementation cannot
keep that, say so once, in the registry:

- `mutates=["graph"]`: the node changes that input in place. Executors run
  every earlier reader of the value first, or hand the node a copy.
- `ordered=True`: the node touches state outside its wires (files, services,
  printing). Ordered nodes of one job keep program order and are never served
  from a replay cache.

Without flags, a node must not change its inputs.

## Signature files

Tools that should not import your code (the checker in the editor, the Rust
core, VS Code) read a signature file instead:

```
kir sig export my_package.nodes -o sigs/        # writes sigs/gbc.kirsig.json
```

Programs name the library with `@use "gbc"` (or `@use "gbc" as g` and call
`g.entity`); the tools find `gbc.kirsig.json` on `--sig-path` or
`KIR_SIG_PATH`. In Python you can pass libraries directly instead:
`compile_source(text, [lib])`.
