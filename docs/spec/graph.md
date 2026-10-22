# The graph view

A `.kirgraph` file is the same program as its text, shown as the node graph an
editor draws. Graph → text produces canonical text; text → graph → text
returns the graph's canonical text. Graph reconstruction normalizes statement
layout; source provenance is preserved by graph ↔ AST conversion, not by a
plain-text hop. Legacy graphs have an entry ambiguity described below.

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

Source-module declarations are optional file-level fields:

```json
{
  "imports": [{"module": "relative/helpers.kir", "alias": "helpers"}],
  "exports": ["expand"]
}
```

They retain declaration order within each list and are omitted when empty.
Imports require aliases; exports are individual names. These are declarations,
not runtime nodes. `uses` retains its existing host-library meaning.

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
| `assign` | `value` | `value` | `in` | `out` | — |
| `value` | — | `value` | — | — | `value` (a literal) |
| `get` | — | `value` | — | — | `name` |
| `set` | `value` | — | — | — | `name` |
| `branch` | `cond` | — | `in` | `true`, `false` | `labels` {port: label} |
| `switch` | `value` | — | `in` | `case_0` … `case_n`, `default` | `cases`, `labels` |
| `merge` | — | — | `in_0` … `in_n` | `out` | `label` (loop entry only) |
| `each` | `items` | `item`, `index` | `in`, `next` | `body`, `done` | `label`, `item`, `index`, `has_index` |
| `collect` | `items`, deferred `value` | `item`, `index`, `results` | `in`, `next` | `body`, `done` | `label`, `item`, `index`, `has_index`, `target` |
| `parallel` | — | — | `in` | `out_0` … `out_n` | `labels` |
| `try` | — | `error` (when named) | `in` | `try`, `except` | `error_name` |
| `dataflow` | — | — | `in` | `out` | `members` (node ids, in order) |
| `inputs` | — | one per parameter | — | `out` | — |
| `outputs` | one per output | — | `in` | — | — |

- **Variables.** `get` and `set` are the variable nodes: name → node → name.
  A `get` is a read of the name at the position of the node its wire goes
  into; a `set` names the output port wired into it, so the write happens when
  that node runs. Neither has control ports. An output port wired into a `set`
  needs no `var`; one output may feed only one `set`.
- **`assign`** is the command `name = value`: its `value` input is a literal
  box or a wire, its output is the variable (a `var` on the port, or a `set`).
  It sits on the control chain like a call.
- **`value`** is a literal as a node, with no control ports; a wire from it is
  the same as writing the literal in the input box it feeds.
- Builtin outputs (`each` item and index, `try` error, `inputs` parameters)
  bind the name of the `set` they feed, else the name in their props.
- A `merge` with a `label` represents a namespace: entering control edges are
  jumps to it. A root merge with **`"entry": true`** explicitly starts with
  ``()jump(`label`)`` followed by `label:`. The encoder emits this optional node
  field when a source jump is directly reached from graph entry and has no
  preceding control edge. Without the marker, an otherwise unentered root
  merge reconstructs only the namespace, never an executable entry jump.
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

## Collect: a deferred body-end input

The control form ``(items)collect(item[, index], `body`, value -> results)``
is a distinct `collect` node, not an ordinary eager call. Its wire-style shape
is:

```json
{
  "id": "collect_1",
  "kind": "collect",
  "props": {
    "label": "body",
    "item": "item",
    "index": null,
    "has_index": false,
    "target": "results"
  },
  "inputs": [
    {"port": "items"},
    {"port": "value", "deferred": "body_end"}
  ],
  "outputs": [
    {"port": "item", "var": "item"},
    {"port": "index", "var": null},
    {"port": "results", "var": "results"}
  ],
  "ctrl_in": ["in", "next"],
  "ctrl_out": ["body", "done"]
}
```

`items` is read on entry. `body` enters the owned namespace with item/index
bindings; each normal body end returns through `next`. Only then is the
`value` input sampled for that iteration. The `deferred: "body_end"` marker
is required: a body-produced value is **not** an input needed before entering
the collect. A literal sample uses the same input with a `value` literal box,
including explicit `null`; a named sample has a data edge to that input.

In wire style, that edge comes from definitions reaching the body's normal
end, not definitions reaching collect entry. With multiple possible writers,
or in variable style, a `get` feeds the deferred input instead. Feedback such
as collect `item` → body computation → collect `value` is intentional control
iteration, not an eager dataflow dependency cycle.

The `results` output becomes available only on successful completion through
`done`, including an empty list for zero iterations. It does not publish a
partial result at `next` or on an exception. In variable style its `set` names
the destination; otherwise the output's `var` and `props.target` retain the
source target. The body cannot read or write this target. Full validation and
execution rules are specified in [collect.md](collect.md).

A collect owns the namespace named by `props.label`, even when that namespace
was declared before the collect in source. The encoder emits the body once,
from the owning node; reconstruction writes the collect and its body namespace
before continuing from `done`. Nested collects have separate body/next/done
regions. A root collect is recognized by its unconnected `in` port even if a
body back edge enters `next`.

The collect statement uses ordinary node `origin`; its namespace origin is
stored under `namespace_origins.body`, independently of editor metadata.
These additions affect only collect graphs: existing `each` and ordinary-call
serialization is unchanged. Older graph readers without `collect` support
must not interpret its deferred input as an eager call argument.

## Source provenance

An optional `origin` object is separate from editor `meta` and `hints`:

```json
{
  "module": "helpers.kir",
  "node_id": "source_4",
  "line": 12,
  "definition": "expand",
  "calls": [{"module": "main.kir", "node_id": "call_2", "line": 8}],
  "generated": "inline"
}
```

`module` and `node_id` are required strings. `line` is an integer or null;
`definition` and `generated` are strings or null; `calls` is a recursive array
of origins, defaulting to `[]`. The encoder includes all six fields; readers
accept omitted optional fields. The source `node_id` is independent of the
editor node's `id`.

- Statement nodes carry `origin`; a definition's graph carries its own
  `origin` separately from origins on body nodes.
- Namespaces have no runtime nodes. Their origins appear in the entering
  node's `namespace_origins` map, keyed by outgoing control port. A labelled
  merge uses `out`; builtins use their arm/body ports.
- Explicit jumps carry `origin` on control edges into labelled merges.
  A merge's node `origin` records the initial jump represented by that merge,
  including an entry jump without a preceding edge. The `entry` marker, not
  provenance, determines whether a root merge executes.
- When any top-level typehint block has an origin, file-level
  `typehint_groups` contains ordered `{"count": N, "origin": ...}` objects
  (origin omitted for an unstamped group). Counts partition the existing
  flattened `typehints` list and preserve block origins.

These fields are omitted when absent. `from_graph(..., with_meta=False)`
removes editor metadata, **not** provenance. No KIR text origin directive is
introduced: writing and reparsing text loses origins and their call stacks.
Consequently, multiple typehint blocks whose distinct origins were preserved
may merge into one block on the next no-origin graph projection; subsequent
text normalization is stable. Graph normalization may also synthesize jumps
or other structure, so provenance is not a bijection with original statements.

## Text → graph

Statements become nodes in order. Control edges follow the rule of
semantics.md: a namespace's body continues after the namespace definition, an
`each` body returns to the `each` node's `next` port, `parallel` arms and both
`@try` branches join the statement after them. Where two or more control
paths reach the same statement, a `merge` node joins them. Literals become
input boxes (`value` on the input port).

Data is drawn in one of two styles, chosen by the caller
(`to_graph(program, env, data=...)`, `kir graph --data ...`):

- **`wires`** (default): a read reached by exactly one write is a data edge
  from that write's output port (or from the `inputs` node for a parameter).
  A name written on several paths is drawn with variables: a `set` on each of
  its writes and a `get` for each read.
- **`variables`**: every read is a `get` and every write a `set`, so data
  always reads name → node → name and control wires stay uncrossed.

Both styles convert back to the same canonical text, and an editor may mix
them freely.

## Graph → text

The walk starts at each node without incoming control edges, and at `each`
or labelled-merge roots whose primary control input is unconnected even when
back edges target their other inputs. A marked merge root executes its entry
jump; an unmarked merge root only declares a namespace. A branch-like
node (`branch`, `switch`, `parallel`, `try`) writes one namespace per output
port; each arm stops at the first node every arm reaches inside the current
loop, and the text continues there. A labelled `merge` writes the loop entry;
when every path leaving the loop meets at one node, the text continues there
after the loop's namespace. Free `call` / `assign` nodes (no control ports)
outside any `dataflow` group form one `@dataflow:` block at the top.

### Compatibility and limits

Older encoders emitted identical graphs for an initial `jump` into a namespace
and for an unentered namespace with the same body. That information cannot be
recovered from the old topology, metadata, or origin. An unmarked root is
therefore conservatively reconstructed as an unentered namespace; regenerate
such graphs from source to obtain `entry: true`. Older decoders may ignore
that marker and cannot guarantee correct entry behavior for these graphs.
The marker is an additive correction for this formerly ambiguous case;
existing golden graphs are unchanged. Ordinary unstamped programs omit all
new declaration/provenance fields.

Graph ↔ AST conversion preserves provenance on represented statements, while
retaining existing graph scope/structuring restrictions. It is not a lossless
source archive: nested definitions/typehint blocks, unresolved jumps, and
unsupported combinations of builtin and jump entry are not made representable
by provenance fields. Text roundtrips preserve declarations but intentionally
do not preserve origins.
