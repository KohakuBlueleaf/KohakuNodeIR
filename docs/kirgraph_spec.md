# KirGraph Format Specification (.kirgraph)

**Version**: 0.1.0-draft

## 1. Overview

KirGraph (`.kirgraph`) is the Level 1 IR for KohakuNodeIR — a JSON-based graph description format that directly represents the visual node graph. It stores the complete topology (nodes + edges) without any execution ordering.

### 1.1 Three-Level IR Architecture

```
Level 1: .kirgraph     →  Level 2: .kir (with @dataflow:, @meta)  →  Level 3: .kir (pure sequential)
(graph topology)           (human-readable, round-trippable)          (engine-ready, no @dataflow:)
```

- **L1 → L2**: Graph compiler determines execution order, places `@dataflow:` blocks, generates variable names
- **L2 → L1**: Decompiler parses `@meta` annotations to recover graph topology
- **L2 → L3**: Dataflow sanitizer expands `@dataflow:` blocks via topological sort

### 1.2 Design Principles

1. **Flat node list** — no hierarchy, no nesting
2. **Explicit edges** — every connection is a separate entry
3. **Self-contained nodes** — each node carries all its port info
4. **Position is metadata** — optional, does not affect semantics
5. **JSON-native** — easy to serialize/deserialize in any language

---

## 2. Format

A `.kirgraph` file is a JSON object with three required fields:

```json
{
  "version": "0.1.0",
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

### 2.1 Node Object

```json
{
  "id": "n1",
  "type": "add",
  "name": "Add",
  "data_inputs": [
    { "port": "a", "type": "float", "default": 0 },
    { "port": "b", "type": "float", "default": 0 }
  ],
  "data_outputs": [
    { "port": "result", "type": "float" }
  ],
  "ctrl_inputs": [ "in" ],
  "ctrl_outputs": [ "out" ],
  "properties": {},
  "meta": {
    "pos": [200, 300],
    "size": [180, 120]
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique node identifier |
| `type` | string | yes | Node type key (e.g., "add", "branch", "value") |
| `name` | string | yes | Display name |
| `data_inputs` | array | yes | Data input port definitions |
| `data_outputs` | array | yes | Data output port definitions |
| `ctrl_inputs` | array | yes | Control input port names (strings) |
| `ctrl_outputs` | array | yes | Control output port names (strings) |
| `properties` | object | no | Type-specific properties (e.g., literal value, code) |
| `meta` | object | no | UI metadata (position, size, color, etc.) |

**Data port object:**

```json
{ "port": "port_name", "type": "float", "default": 0 }
```

- `port`: port name (unique within the node's inputs or outputs)
- `type`: data type hint ("any", "int", "float", "str", "bool", etc.)
- `default`: optional default value (only for inputs, used when not connected)

### 2.2 Edge Object

```json
{
  "type": "data",
  "from": { "node": "n1", "port": "result" },
  "to": { "node": "n2", "port": "a" }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | yes | `"data"` or `"control"` |
| `from` | object | yes | Source: `{ "node": node_id, "port": port_name }` |
| `to` | object | yes | Target: `{ "node": node_id, "port": port_name }` |

**Rules:**
- Data edges: `from` must be a data output, `to` must be a data input
- Control edges: `from` must be a ctrl output, `to` must be a ctrl input
- No self-loops (from.node ≠ to.node)
- Multiple edges to the same input port: last one wins (or error, implementation-defined)

---

## 3. Special Node Types

### 3.1 Branch

```json
{
  "id": "n5",
  "type": "branch",
  "name": "Branch",
  "data_inputs": [{ "port": "condition", "type": "bool" }],
  "data_outputs": [],
  "ctrl_inputs": ["in"],
  "ctrl_outputs": ["true", "false"]
}
```

### 3.2 Merge

```json
{
  "id": "n6",
  "type": "merge",
  "name": "Merge",
  "data_inputs": [],
  "data_outputs": [],
  "ctrl_inputs": ["in_0", "in_1"],
  "ctrl_outputs": ["out"]
}
```

### 3.3 Switch

```json
{
  "id": "n7",
  "type": "switch",
  "name": "Switch",
  "data_inputs": [{ "port": "value", "type": "any" }],
  "data_outputs": [],
  "ctrl_inputs": ["in"],
  "ctrl_outputs": ["case_0", "case_1", "default"],
  "properties": {
    "cases": { "case_0": 0, "case_1": 1 }
  }
}
```

### 3.4 Value

```json
{
  "id": "n8",
  "type": "value",
  "name": "Value",
  "data_inputs": [],
  "data_outputs": [{ "port": "value", "type": "int" }],
  "ctrl_inputs": [],
  "ctrl_outputs": [],
  "properties": {
    "value_type": "int",
    "value": 42
  }
}
```

### 3.5 Parallel

```json
{
  "id": "n9",
  "type": "parallel",
  "name": "Parallel",
  "data_inputs": [],
  "data_outputs": [],
  "ctrl_inputs": ["in"],
  "ctrl_outputs": ["out_0", "out_1"]
}
```

### 3.6 Subgraph (User-Defined)

```json
{
  "id": "n10",
  "type": "my_custom_node",
  "name": "My Filter",
  "data_inputs": [
    { "port": "image", "type": "any" },
    { "port": "threshold", "type": "float", "default": 0.5 }
  ],
  "data_outputs": [{ "port": "filtered", "type": "any" }],
  "ctrl_inputs": ["in"],
  "ctrl_outputs": ["out"],
  "properties": {
    "code": "def node_func(image, threshold=0.5):\n    return image[image > threshold]"
  }
}
```

---

## 4. Full Example

A simple program: generate two numbers, add them, branch on result.

```json
{
  "version": "0.1.0",
  "nodes": [
    {
      "id": "val_a",
      "type": "value",
      "name": "Value A",
      "data_inputs": [],
      "data_outputs": [{ "port": "value", "type": "int" }],
      "ctrl_inputs": [],
      "ctrl_outputs": [],
      "properties": { "value_type": "int", "value": 10 },
      "meta": { "pos": [100, 100], "size": [160, 80] }
    },
    {
      "id": "val_b",
      "type": "value",
      "name": "Value B",
      "data_inputs": [],
      "data_outputs": [{ "port": "value", "type": "int" }],
      "ctrl_inputs": [],
      "ctrl_outputs": [],
      "properties": { "value_type": "int", "value": 20 },
      "meta": { "pos": [100, 250], "size": [160, 80] }
    },
    {
      "id": "add1",
      "type": "add",
      "name": "Add",
      "data_inputs": [
        { "port": "a", "type": "float", "default": 0 },
        { "port": "b", "type": "float", "default": 0 }
      ],
      "data_outputs": [{ "port": "result", "type": "float" }],
      "ctrl_inputs": ["in"],
      "ctrl_outputs": ["out"],
      "meta": { "pos": [350, 150], "size": [180, 120] }
    },
    {
      "id": "cmp1",
      "type": "greater_than",
      "name": "Greater Than",
      "data_inputs": [
        { "port": "a", "type": "float", "default": 0 },
        { "port": "b", "type": "float", "default": 25 }
      ],
      "data_outputs": [{ "port": "result", "type": "bool" }],
      "ctrl_inputs": ["in"],
      "ctrl_outputs": ["out"],
      "meta": { "pos": [600, 150], "size": [180, 120] }
    },
    {
      "id": "br1",
      "type": "branch",
      "name": "Branch",
      "data_inputs": [{ "port": "condition", "type": "bool" }],
      "data_outputs": [],
      "ctrl_inputs": ["in"],
      "ctrl_outputs": ["true", "false"],
      "meta": { "pos": [850, 150], "size": [180, 120] }
    },
    {
      "id": "print_big",
      "type": "print",
      "name": "Print Big",
      "data_inputs": [{ "port": "value", "type": "any" }],
      "data_outputs": [],
      "ctrl_inputs": ["in"],
      "ctrl_outputs": ["out"],
      "meta": { "pos": [1100, 50], "size": [180, 100] }
    },
    {
      "id": "print_small",
      "type": "print",
      "name": "Print Small",
      "data_inputs": [{ "port": "value", "type": "any" }],
      "data_outputs": [],
      "ctrl_inputs": ["in"],
      "ctrl_outputs": ["out"],
      "meta": { "pos": [1100, 250], "size": [180, 100] }
    }
  ],
  "edges": [
    { "type": "data", "from": { "node": "val_a", "port": "value" }, "to": { "node": "add1", "port": "a" } },
    { "type": "data", "from": { "node": "val_b", "port": "value" }, "to": { "node": "add1", "port": "b" } },
    { "type": "data", "from": { "node": "add1", "port": "result" }, "to": { "node": "cmp1", "port": "a" } },
    { "type": "data", "from": { "node": "cmp1", "port": "result" }, "to": { "node": "br1", "port": "condition" } },
    { "type": "data", "from": { "node": "add1", "port": "result" }, "to": { "node": "print_big", "port": "value" } },
    { "type": "data", "from": { "node": "add1", "port": "result" }, "to": { "node": "print_small", "port": "value" } },

    { "type": "control", "from": { "node": "add1", "port": "out" }, "to": { "node": "cmp1", "port": "in" } },
    { "type": "control", "from": { "node": "cmp1", "port": "out" }, "to": { "node": "br1", "port": "in" } },
    { "type": "control", "from": { "node": "br1", "port": "true" }, "to": { "node": "print_big", "port": "in" } },
    { "type": "control", "from": { "node": "br1", "port": "false" }, "to": { "node": "print_small", "port": "in" } }
  ]
}
```

This compiles to Level 2 KIR:

```kir
# Value nodes without control wires → @dataflow: block
@dataflow:
    @meta node_id="val_a" pos=(100, 100) size=[160, 80]
    val_a_value = 10
    @meta node_id="val_b" pos=(100, 250) size=[160, 80]
    val_b_value = 20

# Control-connected chain
@meta node_id="add1" pos=(350, 150) size=[180, 120]
(val_a_value, val_b_value)add(add1_result)

@meta node_id="cmp1" pos=(600, 150) size=[180, 120]
(add1_result, 25)greater_than(cmp1_result)

@meta node_id="br1" pos=(850, 150) size=[180, 120]
(cmp1_result)branch(`br1_true`, `br1_false`)
br1_true:
    @meta node_id="print_big" pos=(1100, 50) size=[180, 100]
    (add1_result)print()
br1_false:
    @meta node_id="print_small" pos=(1100, 250) size=[180, 100]
    (add1_result)print()
```

Which compiles to Level 3 (execution KIR, `@dataflow:` expanded, `@meta` stripped):

```kir
val_a_value = 10
val_b_value = 20
(val_a_value, val_b_value)add(add1_result)
(add1_result, 25)greater_than(cmp1_result)
(cmp1_result)branch(`br1_true`, `br1_false`)
br1_true:
    (add1_result)print()
br1_false:
    (add1_result)print()
```

Note: The `@dataflow:` block is expanded (its two assignments are inlined in topological order) and all `@meta` annotations are removed by `StripMetaPass`. The resulting L3 is pure sequential KIR that the interpreter runs directly.

---

## 5. L1 → L2 Compilation Rules

### 5.1 Variable Naming

Each data output port gets a variable name: `{node_id}_{port_name}`

Example: node `add1`, port `result` → `add1_result`

### 5.2 Data Input Resolution

For each data input port on a node:
1. If connected via a data edge → use the source's variable name
2. If not connected but has `default` → use the literal value
3. If not connected and no default → use literal `0` (fallback)

### 5.3 Control Flow Partitioning

The compiler separates nodes into two groups based on control-edge connectivity:

1. **Control-connected nodes**: Have at least one control edge (in or out). Emitted in control-wire traversal order.
2. **Independent unconnected nodes**: No control edges and no data inputs from control-connected nodes. Wrapped in a single `@dataflow:` block placed at the top of the output program.
3. **Dependent unconnected nodes**: No control edges but their data inputs come (transitively) from control-connected nodes. Wrapped in `@dataflow:` blocks placed immediately after the control node that satisfies all their data inputs, at the correct nesting depth.

This means `@dataflow:` blocks can appear:
- At the top level (for independent value nodes)
- Inside namespace bodies (for data nodes whose inputs are produced inside a loop or branch)
- At the top level after a control chain (for data nodes dependent on control-chain outputs)

### 5.4 Branch/Switch/Merge/Parallel

- **Branch**: Emit `(cond)branch(`true_label`, `false_label`)`. Each ctrl output becomes a namespace containing the downstream control chain.
- **Switch**: Emit `(val)switch(case_val=>`label`, ...)`. Each ctrl output becomes a namespace.
- **Merge (post-branch)**: Code naturally converges after the namespace blocks end — no explicit statement needed.
- **Merge (loop entry)**: A merge node with an unconnected `entry` ctrl input marks the loop entry point. The compiler emits `()jump(`ns_{merge_id}`)` followed by a `ns_{merge_id}:` namespace containing the loop body. The backward edge (from branch `true` back to the merge) becomes `()jump(`ns_{merge_id}`)` inside the branch namespace.
- **Parallel**: Emit `()parallel(`label1`, `label2`, ...)` with a namespace per ctrl output.

The `@meta` for a merge node is attached to the `jump` statement that precedes the namespace, not to the namespace definition itself. This allows the decompiler to recover the merge node's position.

### 5.5 @meta Annotations

Each node emits `@meta node_id="..." pos=(x, y)` before its KIR statement. Additional `meta` fields on the node (e.g., `size`) are also included.

- **FuncCall / Branch / Switch / Parallel / Jump**: `@meta` is stored in the statement's `metadata` field.
- **Assignment** (Value nodes): `@meta` is also stored in the statement's `metadata` field. The `StripMetaPass` and decompiler both handle this correctly.

This enables full L2 → L1 decompilation from annotated KIR text.

---

## 6. L2 → L1 Decompilation Rules

Decompilation is a two-pass process implemented by `KirGraphDecompiler`.

### Pass 1: Node Creation and Control Edges

Walk all statements recursively (including inside `@dataflow:` blocks and `Namespace` bodies):

1. For each statement with `@meta node_id=...`, create a `KGNode`:
   - `Assignment` → `type: "value"`, value and type from the RHS literal
   - `FuncCall` → `type: func_name`, data input/output ports from statement args/outputs
   - `Branch` → `type: "branch"`, `ctrl_outputs: ["true", "false"]`
   - `Switch` → `type: "switch"`, `ctrl_outputs` and `properties.cases` from the case list
   - `Parallel` → `type: "parallel"`, `ctrl_outputs` from the label list
   - `Jump` to `ns_{id}` → `type: "merge"` node with `ctrl_inputs: ["entry", "back"]`; `@meta` attached to the jump carries the merge node's position
2. Emit control edges between sequentially adjacent nodes in the same scope
3. For `branch`/`switch`/`parallel`, connect each ctrl output port to the first node inside the corresponding namespace body

### Pass 2: Data Edges

Walk all statements again. For each input that is an `Identifier`, attempt to split the variable name as `{node_id}_{port_name}` matching a known node id. If successful, create a data edge from `(source_node, port)` to `(target_node, target_port)`.

The split uses the longest matching known node-id prefix first, then falls back to the last-underscore regex pattern.

### Port Name Convention

Variable naming `{node_id}_{port_name}` (e.g., `add1_result` → node `add1`, port `result`) is the mechanism that makes data edge recovery reliable without additional metadata. Output variables are registered during pass 1; data edges are wired during pass 2.

### Position Recovery

`@meta pos=(x, y)` is read from each statement's annotation and stored in `KGNode.meta["pos"]`. Nodes without a `pos` annotation receive auto-generated grid positions.
