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
    @meta node_id="val_a" pos=(100, 100)
    val_a_value = 10

    @meta node_id="val_b" pos=(100, 250)
    val_b_value = 20

# Control-connected chain
@meta node_id="add1" pos=(350, 150)
(val_a_value, val_b_value)add(add1_result)

@meta node_id="cmp1" pos=(600, 150)
(add1_result, 25)greater_than(cmp1_result)

@meta node_id="br1" pos=(850, 150)
(cmp1_result)branch(`br1_true`, `br1_false`)
br1_true:
    @meta node_id="print_big" pos=(1100, 50)
    (add1_result)print()
br1_false:
    @meta node_id="print_small" pos=(1100, 250)
    (add1_result)print()
```

Which compiles to Level 3 (execution KIR):

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

---

## 5. L1 → L2 Compilation Rules

### 5.1 Variable Naming

Each data output port gets a variable name: `{node_id}_{port_name}`

Example: node `add1`, port `result` → `add1_result`

### 5.2 Data Input Resolution

For each data input port on a node:
1. If connected via a data edge → use the source's variable name
2. If not connected but has `default` → use the literal value
3. If not connected and no default → compilation error

### 5.3 Control Flow Partitioning

1. **Control-connected nodes**: Have at least one control edge (in or out). Emit in control-wire order.
2. **Unconnected nodes**: No control edges at all. Wrap in `@dataflow:` block, placed at the position where all their data inputs are available.

### 5.4 Branch/Switch/Merge/Parallel

- **Branch**: Emit `(cond)branch(...)`. Each ctrl output becomes a namespace containing the downstream chain.
- **Switch**: Same pattern with `(val)switch(...)`.
- **Merge**: Multiple ctrl inputs converge. For post-branch merge: implicit (code continues after namespaces). For loop merge (backward edge): emit namespace + jump pattern.
- **Parallel**: Emit `()parallel(...)` with namespace per output.

### 5.5 @meta Annotations

Each node emits `@meta node_id="..." pos=(x, y)` before its KIR statement. This enables L2 → L1 decompilation.

---

## 6. L2 → L1 Decompilation Rules

1. Parse the `.kir` file
2. For each statement with `@meta node_id=...`:
   - Create a node with the given id
   - Infer type from the statement (Assignment→value, FuncCall→function type, Branch→branch, etc.)
   - Extract port names from the statement's inputs/outputs
3. For each variable reference:
   - If it matches `{node_id}_{port_name}` pattern → create a data edge
4. For namespace/branch/switch structure:
   - Reconstruct control edges from the control flow topology
5. Recover positions from `@meta pos=(...)`
