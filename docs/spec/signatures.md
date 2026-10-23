# Signatures and `@use`

The checker, the Rust core, editors and executors need each node's ports,
types and flags without importing the code that implements it (which may load
models). A node library therefore exports a signature file.

## Signature file

`<library>.kirsig.json`:

```json
{
  "kirsig": 1,
  "library": "gbc.nodes",
  "nodes": [
    {
      "name": "entity",
      "inputs": [
        {"name": "crop", "type": "Image"},
        {"name": "box", "type": "Box"},
        {"name": "max_tokens", "type": "int", "default": 256}
      ],
      "outputs": [{"name": "node", "type": "Node"}],
      "flags": {"mutates": [], "ordered": false},
      "doc": "Caption one crop."
    }
  ]
}
```

- `type` uses the type syntax of language.md; missing means `_`.
- `default` is a JSON literal; an input without it is required.
- `flags` may be omitted when empty.

Libraries containing typed record schemas use `"kirsig": 2` and an ordered
`records` array; node-only libraries retain format 1. Schema fields require explicit
types, and construction/projection/replacement signatures are derived on load
rather than duplicated in `nodes`. See [records.md](records.md) for the schema,
value semantics, validation, and compatibility contract.

## `@use`

```
@use "gbc.nodes"
@use "kir.std"
@use "comfy.core" as comfy
```

`@use` lines come first in a file. Each names a library; its nodes become
callable by name, or by `alias.name` when an alias is given. A node name found
in two unaliased libraries is an error at its call sites (checks.md). `@def`
names shadow library names in their file.

Resolution of `"lib"`, first match wins:

1. a path ending in `.kirsig.json`, relative to the `.kir` file;
2. `lib.kirsig.json` in each directory of the signature path: the CLI
   `--sig-path` option, then the `KIR_SIG_PATH` environment variable
   (`os.pathsep`-separated).

## The standard library `kir.std`

Small pure nodes most programs need (`add`, `sub`, `mul`, `div`, `less`,
`less_equal`, `equal`, `not`, `len`, `item_at`, `append`, `concat`,
`to_str`, ...). It ships with the reference implementation and the Rust core,
is always available without `@use`, and is shadowed by any other library or
`@def` that defines the same name. It also includes the ordered effects
`print_value` and `emit(topic: str, payload: _)` (zero outputs). Standard `emit`
produces a committed semantic event; only the maintained standard identity has
that behavior, while user shadows remain ordinary calls. See [events.md](events.md).

Separately, the `expand_each` pass uses a few internal nodes under the
reserved `kir.` prefix (passes.md). Programs may not call them directly.

## Python registry

```python
from kohakunode import NodeLibrary

lib = NodeLibrary("gbc.nodes")


@lib.node(outputs=["node"])
def entity(crop: Image, box: Box, max_tokens: int = 256) -> Node:
    """Caption one crop."""


@lib.node(outputs=["graph"], mutates=["graph"])
def attach(graph: Graph, node: Node) -> Graph: ...


@lib.node(ordered=True)
def append_jsonl(log: str, record: dict) -> None: ...
```

- Inputs, types and defaults come from the function signature; outputs from
  `outputs=` (default: one output named `result`, none when the return
  annotation is `None`).
- A node with several outputs returns a tuple in output order.
- `kir sig export gbc.nodes -o gbc.nodes.kirsig.json` imports the module that
  defines the library and writes its signature file.

Executors map node names to implementations themselves; the signature file is
the static program/node contract for ports, types, defaults, schemas, and effects.
Execution policy and cross-invocation reuse eligibility are separately bound
executor contracts. An empty effect declaration does not prove determinism or
cache eligibility; see [execution-contract.md](execution-contract.md#logical-invocations-attempts-and-reuse-eligibility).
This distinction adds no KIR syntax or signature flag.
