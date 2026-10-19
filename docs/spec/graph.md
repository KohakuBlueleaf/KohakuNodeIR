# The graph view

A `.kirgraph` file is the same program as its text, shown as the node graph an
editor draws. Graph → text produces canonical text; text → graph → text
returns that canonical text, and for canonical text the round trip is the
identity. Behaviour is always preserved.

## File

```json
{
  "kirgraph": 2,
  "uses": [{"library": "gbc", "alias": null}],
  "graphs": [
    {"name": "main", "nodes": [], "edges": []},
    {"name": "expand", "nodes": [], "edges": [],
     "params": [{"name": "image", "type": "Image"}, {"name": "box", "type": "int", "default": 2}],
     "outputs": [{"name": "node", "type": "Node?"}]}
  ],
  "mode": "dataflow",
  "typehints": [{"name": "crop", "inputs": ["Image", "Box"], "outputs": ["Image"]}]
}
```

`main` is the top level; every `@def` is one more graph. `mode` and
`typehints` appear only when the program has them. Nodes are listed in the
order they are created (statement order); edges are sorted by (target node,
target port, source node, source port).

## Nodes

```json
{
  "id": "entity_3",
  "kind": "call",
  "name": "entity",
  "inputs": [{"port": "crop", "type": "Image"}, {"port": "max_tokens", "keyword": true, "value": 64}],
  "outputs": [{"port": "node", "var": "node", "type": "Node"}],
  "ctrl_in": ["in"],
  "ctrl_out": ["out"],
  "hints": {"max_wait_ms": 5},
  "meta": {"pos": [340, 420]}
}
```

- `id`: from `@meta node_id`, else `<name or kind>_<n>` (dots replaced by
  `_`, `n` counting nodes in creation order).
- `inputs`: one entry per input the call gives, in text order. `keyword`
  marks a keyword input; `value` holds a literal given in place of a wire.
  Port names come from the node's signature (`in<i>` when unknown).
- `outputs`: `var` is the name the text binds; `"var": null` is a discarded
  `_` output; an output without `var` is named `<id>_<port>`.
- `ctrl_in` / `ctrl_out` list the control ports. Simple statements on a
  control chain have `["in"]` / `["out"]`; members of a `dataflow` group have
  none.
- `hints` (`@hint`) and `meta` (`@meta` without `node_id`) only when present.

| kind | data in | data out | control in | control out | props |
|---|---|---|---|---|---|
| `call` | from signature | from signature | `in` | `out` | — |
| `value` | — | `value` | `in` | `out` | `value` (a literal) |
| `set` | `value` | `value` | `in` | `out` | `name`, `copy` |
| `get` | — | `value` | — | — | `name` |
| `branch` | `cond` | — | `in` | `true`, `false` | `labels` {port: label} |
| `switch` | `value` | — | `in` | `case_0` … `case_n`, `default` | `cases`, `labels` |
| `merge` | — | — | `in_0` … `in_n` | `out` | `label` (loop entry only) |
| `each` | `items` | `item`, `index` | `in`, `next` | `body`, `done` | `label`, `item`, `index`, `has_index` |
| `parallel` | — | — | `in` | `out_0` … `out_n` | `labels` |
| `try` | — | `error` (when named) | `in` | `try`, `except` | `error_name` |
| `dataflow` | — | — | `in` | `out` | `members` (node ids, in order) |
| `inputs` | — | one per parameter | — | `out` | — |
| `outputs` | one per output | — | `in` | — | — |

- A `set` with `copy: true` is the assignment `name = other`. A `set` without
  it only shows that a name is written on several paths: it sits after each
  such write, and every read of the name is a `get`. In text both collapse to
  plain writes and reads of the name.
- A `merge` with a `label` is a loop entry: `()jump(`label`)` followed by
  `label:`; every other edge into it is a `jump` back.
- A `dataflow` node stands for a `@dataflow:` block on the control chain; its
  members are free nodes (no control ports).
- Literals in `value` fields are JSON, except tuples (`{"tuple": [...]}`),
  dicts (`{"dict": {...}}`, or `{"pairs": [[k, v], ...]}` for non-string
  keys).

## Edges

```json
{"kind": "data", "from": {"node": "crop_2", "port": "crop"}, "to": {"node": "entity_3", "port": "crop"}}
```

`kind` is `data` or `ctrl`. An input port takes at most one data edge.

## Text → graph

Statements become nodes in order. Control edges follow the rule of
semantics.md: a namespace's body continues after the namespace definition, an
`each` body returns to the `each` node's `next` port, `parallel` arms and both
`@try` branches join the statement after them. Where two or more control
paths reach the same statement, a `merge` node joins them. A read reached by
exactly one write is a data edge from that write's output port (or from the
`inputs` node for a parameter); otherwise it is a `get`.

## Graph → text

The walk starts at each node without incoming control edges. A branch-like
node (`branch`, `switch`, `parallel`, `try`) writes one namespace per output
port; each arm stops at the first node every arm reaches inside the current
loop, and the text continues there. A labelled `merge` writes the loop entry;
when every path leaving the loop meets at one node, the text continues there
after the loop's namespace. Free `call` / `value` / copy-`set` nodes outside
any `dataflow` group form one `@dataflow:` block at the top.
