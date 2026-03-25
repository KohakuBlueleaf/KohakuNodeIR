# Kohaku Node IR - Specification

**Version**: 0.1.0-draft

---

# Part I: KIR Language

## 1. Overview

Kohaku Node IR (`.kir`) is an intermediate representation language designed for node-based visual programming systems. It serves as middleware between node UI frontends and backend execution engines, allowing different node UI designs to share the same backend.

The language supports both:
- **Control-flow** visual programming (Scratch, Lego Mindstorms, Fischer Technik)
- **Data-flow** visual programming (ComfyUI, Blender node editor)

### 1.1 Three-Level IR Architecture

```
Level 1: .kirgraph          Level 2: .kir                    Level 3: .kir
(graph topology)             (human-readable IR)              (execution-ready IR)
JSON: nodes + edges          @dataflow: scopes, @meta         pure sequential logic
UI-native format             round-trippable to L1            no @dataflow:, no @meta
```

| Level | Format | Purpose | Contains |
|-------|--------|---------|----------|
| L1 | `.kirgraph` (JSON) | Graph topology from node UI | Node list + edge list, positions, properties |
| L2 | `.kir` (text) | Human-readable IR, interchange format | `@dataflow:` scopes, `@meta` annotations, control flow |
| L3 | `.kir` (text) | Engine-ready IR | Pure sequential statements, `@dataflow:` blocks expanded |

**Compilation pipeline:**
- **L1 → L2**: Graph compiler determines execution order, places `@dataflow:` blocks for unconnected nodes, generates variable names, emits `@meta` for round-tripping
- **L2 → L3**: Dataflow sanitizer expands `@dataflow:` blocks via topological sort, optionally strips `@meta`
- **L2 → L1**: Decompiler reconstructs graph topology from `@meta` annotations and variable references
- **L3 → Engine**: Standard sequential execution

Level 2 (`.kir`) is the **pivot format** — it can convert to both L1 (for UI) and L3 (for execution).

### 1.2 Design Principles

1. **Always sequential**: Execution is strictly line-by-line, top to bottom.
2. **No built-in functions**: The language standard requires zero built-in functions from the backend. All domain functions are backend-provided.
3. **Built-in utilities only**: A small set of control-flow utilities (`branch`, `switch`, `jump`, `parallel`) are part of the language itself.
4. **Backend-agnostic**: The IR describes the node graph. Function registration and resolution is the backend's responsibility.
5. **Round-trippable**: Metadata annotations allow UIs to reconstruct visual layout from IR.

---

## 2. Lexical Structure

### 2.1 Comments

```
# Single line comment (hash)
## Section comment (double hash, conventionally used for documentation sections)
```

Comments extend to end of line. There are no block comments.

### 2.2 Identifiers

Identifiers are used for variable names and function names.

```
variable_name
my_func
image_processing.blur    # dotted names are valid identifiers for functions
```

Rules:
- Start with a letter or underscore
- Contain letters, digits, underscores
- Function names may additionally contain dots (`.`) for namespacing
- `_` alone is reserved as the wildcard/discard symbol

### 2.3 Literals

Literals follow Python syntax:

| Type   | Examples                          |
|--------|-----------------------------------|
| int    | `42`, `-1`, `0xFF`                |
| float  | `3.14`, `-0.5`, `1e-3`           |
| bool   | `True`, `False`                   |
| string | `"hello"`, `'world'`, `"""..."""` |
| None   | `None`                            |
| list   | `[1, 2, 3]`, `["a", "b"]`        |
| dict   | `{"key": "value", "n": 42}`      |

### 2.4 Label References

Namespace labels referenced in control-flow utilities use backtick quoting:

```
`my_namespace`
`loop_body`
```

---

## 3. Statements

A `.kir` file is a sequence of statements, one per line (with multi-line continuation via open parentheses). Blank lines and comment-only lines are ignored.

### 3.1 Variable Assignment

```
variable = expression
```

Where expression is a literal value or an existing variable name.

```
x = 42
name = "hello"
y = x
sizes = [1, 2, 3]
```

Variable reassignment (override) is allowed and expected, especially inside loops.

Assignments may carry `@meta` annotations, just like function calls. This is used by the L1→L2 compiler to annotate Value nodes:

```
@meta node_id="val_a" pos=(100, 200)
val_a_value = 10
```

The executor ignores the annotation. The `@meta` is placed immediately before the assignment statement using the same rules as for function calls (see [Section 3.4](#34-metadata-annotation)).

### 3.2 Function Call

```
(input_args)function_name(output_names)
```

- **input_args**: comma-separated list of positional arguments followed by optional keyword arguments
  - Positional: variable names or literal values
  - Keyword: `name=value` where value is a variable or literal
- **function_name**: identifier (may contain dots)
- **output_names**: comma-separated list of variable names to bind results to
  - Use `_` to discard an output

Examples:
```
("./data/test.bin")load_data(x1, x2)
(x1, x2, mode="fast")process(result, _)
()generate_random(value)
(x1, "output.png")save()
```

#### Multi-line Calls

When parentheses are open, the statement continues on the next line:

```
(
    x1, x2,
    mode="bicubic",
    threshold=0.5
)complex_filter(
    filtered,
    confidence
)
```

### 3.3 Namespace Definition

```
label_name:
    indented_body
```

A namespace is a labeled, indented block. See [Section 4: Execution Model](#4-execution-model) for semantics. See [Section 6: Dataflow](#6-dataflow) for the `@dataflow:` block variant, which is syntactically similar but has dependency-ordered (not sequential) semantics.

### 3.4 Metadata Annotation

```
@meta key=value key2=value2 ...
```

Attaches non-execution metadata to the **next** statement. Multiple `@meta` lines can precede a single statement. Values follow literal syntax (including tuples for positions).

```
@meta node_id="n01" pos=(120, 300)
@meta color="blue" label="My Node"
(x1)process(x2)
```

The executor MUST ignore metadata. UIs use metadata for round-tripping layout information.

### 3.5 Subgraph Definition

```
@def (input_params)name(output_params):
    body
```

Defines a reusable subgraph (equivalent to node groups in Blender, custom blocks in Scratch). Input params may have defaults. The subgraph is called using standard function call syntax.

```
@def (image, strength=1.0)preprocess(cleaned):
    (image)denoise(denoised)
    (denoised, amount=strength)normalize(cleaned)

# call it like any function
(my_image)preprocess(result)
(my_image, strength=2.0)preprocess(result2)
```

### 3.6 Mode Declaration

```
@mode dataflow
```

Declared at the top of a file. See [Section 5: Dataflow Mode](#5-dataflow-mode).

---

## 4. Execution Model

### 4.1 Sequential Execution

Execution proceeds line by line, top to bottom. There is no implicit parallelism or dependency-based ordering. Every `.kir` program (after dataflow compilation if applicable) executes sequentially.

### 4.2 Namespace Rules

Namespaces are the core scoping and control-flow mechanism.

**Rule 1 — Skip on encounter**: During sequential execution, when a namespace definition (`label:`) is encountered, the entire indented block is **skipped**. Execution continues at the next line after the block.

**Rule 2 — Explicit entry only**: A namespace can only be entered via the built-in utilities: `branch`, `switch`, `jump`, or `parallel`.

**Rule 3 — Automatic exit**: When execution reaches the end of a namespace's indented block, it continues at the next line in the parent scope. This is automatic — no explicit "return" or "end" statement is needed.

**Rule 4 — Explicit entry, automatic exit**: A lower-level (parent/root) scope cannot enter a higher-level (child) namespace without an explicit `branch`, `switch`, `jump`, or `parallel`. But when a higher-level (child) namespace block ends naturally, execution automatically continues in the lower-level (parent) scope.

**Rule 5 — Nesting**: Namespaces can be nested to any depth. Inner namespaces follow the same rules: skipped during sequential execution within their parent, entered only via explicit control flow.

**Rule 6 — Variable visibility**: All variables exist in a single flat scope. Variables assigned inside a namespace are visible everywhere after assignment. There is no block scoping.

### 4.3 Example Trace

```
x = 1                          # 1. executes, x = 1
(x)check(cond)                 # 2. executes, cond = ...

(cond)branch(`a`, `b`)         # 3. goto `a` or `b`
a:                              #    (skipped if branch chose `b`)
    (x)process_a(y)            # 4a. executes if branch chose `a`
b:                              #    (skipped if branch chose `a`)
    (x)process_b(y)            # 4b. executes if branch chose `b`

(y)final(result)               # 5. always executes after branch
```

Assuming `cond` is True (branch goes to `a`):
1. `x = 1`
2. `check` runs
3. `branch` → goto `a`
4. Inside `a`: `process_a` runs, `a` block ends
5. Next line in parent: `b:` — namespace, **skipped**
6. Next line: `(y)final(result)` — executes

---

## 5. Built-in Utilities

These are the ONLY language-level constructs beyond assignment and function call. They are NOT functions — they are control-flow primitives.

> **Note on store/load**: The `store` and `load` node types registered in the backend are ordinary identity functions (`value → value`). They have no special meaning in the KIR language itself. They exist as a visual convention for data-passing patterns in the UI. In compiled KIR they become standard function calls or are collapsed into variable assignments.

### 5.1 branch

```
(condition)branch(`true_label`, `false_label`)
```

- **Input**: A single boolean variable
- **Arguments**: Two backtick-quoted namespace labels
- **Behavior**: Goto `true_label` if condition is True, `false_label` if False

The condition must be a variable, not an expression. To evaluate complex conditions, use a backend function that returns a boolean.

### 5.2 switch

```
(value)switch(val1=>`label1`, val2=>`label2`, ..., _=>`default_label`)
```

- **Input**: A single value variable
- **Arguments**: `value=>label` pairs, `_` for default
- **Behavior**: Goto the label matching the value. If no match and no default, behavior is undefined (implementations should error).

### 5.3 jump

```
()jump(`label`)
```

- **Input**: None
- **Arguments**: One backtick-quoted namespace label
- **Behavior**: Unconditional goto. Transfers execution to the target namespace.

`jump` is the only way to create loops (by jumping back to an earlier namespace).

### 5.4 parallel

```
()parallel(`label1`, `label2`, ...)
```

- **Input**: None
- **Arguments**: One or more backtick-quoted namespace labels
- **Behavior**: Execute all listed namespaces. Execution order between them is **not guaranteed**. Execution continues at the next line only after **all** namespaces complete.

**Important**: `parallel` does NOT guarantee actual parallel execution. It guarantees that execution order between the listed namespaces is not ensured. The backend MAY execute them concurrently, or sequentially in any order. The semantic contract is: these namespaces have no ordering dependency on each other.

---

## 6. Dataflow

### 6.1 Scoped `@dataflow:` Blocks

```
@dataflow:
    (x, y)multiply(product)
    ()generate(y)
    (product)finalize(output)
```

A `@dataflow:` block is a scoped region where statement execution order is determined by **data dependencies**, not line order. The backend compiles each block by topologically sorting its statements before execution.

**Semantics:**
- Statements inside `@dataflow:` are reordered by the compiler based on which outputs each statement depends on
- The block is expanded (inlined) at its position in the parent scope
- After compilation, the `@dataflow:` wrapper is removed — only sorted sequential statements remain
- Self-referencing updates (e.g., `(total, x)add(total)`) are NOT treated as cycles — the output name is excluded from its own dependency set

**Scoped `@dataflow:` can appear:**
- At the top level of a program
- Inside a namespace (e.g., inside a loop body — re-executes each iteration)
- Inside a `@def` subgraph body
- Multiple `@dataflow:` blocks can appear in the same file

**Example** — see `examples/kir_basics/mixed_mode.kir` for a complete mixed control-flow and dataflow program.

### 6.2 File-Level `@mode dataflow`

```
@mode dataflow
```

When declared at the top of a file, the entire file body is treated as a single `@dataflow:` block. This is equivalent to wrapping all statements in `@dataflow:`.

**Constraint**: Files with `@mode dataflow` must NOT contain control-flow constructs (`branch`, `switch`, `jump`, namespaces). For mixed control+dataflow, use scoped `@dataflow:` blocks instead.

---

## 7. Grammar Summary (EBNF-style)

```
program        = { statement }
statement      = assignment | func_call | namespace_def | dataflow_block | meta_anno | subgraph_def | mode_decl | comment

assignment     = IDENT "=" expression
expression     = literal | IDENT

func_call      = "(" arg_list ")" FUNC_IDENT "(" output_list ")"
arg_list       = [ arg { "," arg } ]
arg            = expression | keyword_arg
keyword_arg    = IDENT "=" expression
output_list    = [ output { "," output } ]
output         = IDENT | "_"

namespace_def  = IDENT ":" NEWLINE INDENT { statement } DEDENT

meta_anno      = "@meta" { IDENT "=" expression }
subgraph_def   = "@def" "(" param_list ")" IDENT "(" output_list ")" ":" NEWLINE INDENT { statement } DEDENT
dataflow_block = "@dataflow" ":" NEWLINE INDENT { statement } DEDENT
mode_decl      = "@mode" IDENT

literal        = INT | FLOAT | STRING | BOOL | NONE | list_lit | dict_lit
list_lit       = "[" [ expression { "," expression } ] "]"
dict_lit       = "{" [ dict_pair { "," dict_pair } ] "}"
dict_pair      = expression ":" expression

FUNC_IDENT     = IDENT { "." IDENT }
```

---

## 8. Reserved Words and Symbols

### Reserved Identifiers
- `True`, `False`, `None` — literal values
- `_` — wildcard/discard output
- `branch`, `switch`, `jump`, `parallel` — built-in utilities

### Reserved Syntax
- `@meta` — metadata annotation
- `@def` — subgraph definition
- `@mode` — mode declaration
- Backtick quotes (`` ` ``) — namespace label references

---

## 9. Conformance

### 9.1 Backend Requirements

A conforming backend MUST:
1. Provide a function registry that maps function names to implementations
2. Execute IR statements sequentially, respecting namespace rules
3. Implement all four built-in utilities (`branch`, `switch`, `jump`, `parallel`)
4. Ignore `@meta` annotations during execution
5. Support `@mode dataflow` by compiling to sequential IR before execution

A conforming backend MAY:
1. Execute `parallel` namespaces concurrently or in any sequential order
2. Support additional `@`-directives as extensions (must be prefixed to avoid conflicts)
3. Add caching or optimization as long as observable behavior matches sequential execution

### 9.2 UI Requirements

A conforming UI MUST:
1. Emit valid `.kir` syntax
2. Preserve round-trip fidelity: loading and re-saving a `.kir` file should not lose information

A conforming UI MAY:
1. Emit `@mode dataflow` and rely on the backend for topological sorting
2. Emit additional `@meta` fields for UI-specific layout data

---

# Part II: KirGraph Format

## 10. Overview

KirGraph (`.kirgraph`) is the Level 1 IR — a JSON-based graph description format that directly represents the visual node graph. It stores the complete topology (nodes + edges) without any execution ordering.

### 10.1 Design Principles

1. **Flat node list** — no hierarchy, no nesting
2. **Explicit edges** — every connection is a separate entry
3. **Self-contained nodes** — each node carries all its port info
4. **Position is metadata** — optional, does not affect semantics
5. **JSON-native** — easy to serialize/deserialize in any language

---

## 11. Format

A `.kirgraph` file is a JSON object with three required fields:

```json
{
  "version": "0.1.0",
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

### 11.1 Node Object

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

### 11.2 Edge Object

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

## 12. Special Node Types

### 12.1 Branch

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

### 12.2 Merge

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

### 12.3 Switch

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

### 12.4 Value

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

### 12.5 Parallel

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

### 12.6 Subgraph (User-Defined)

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

## 13. Full Example

See `examples/kirgraph_pipeline/` for a complete L1 → L2 → L3 pipeline demo with source `.kirgraph` and compiled `.kir` outputs.

---

# Part III: IR Pipeline

## 14. L1 → L2 Compilation Rules

### 14.1 Variable Naming

Each data output port gets a variable name: `{node_id}_{port_name}`

Example: node `add1`, port `result` → `add1_result`

### 14.2 Data Input Resolution

For each data input port on a node:
1. If connected via a data edge → use the source's variable name
2. If not connected but has `default` → use the literal value
3. If not connected and no default → use literal `0` (fallback)

### 14.3 Control Flow Partitioning

The compiler separates nodes into two groups based on control-edge connectivity:

1. **Control-connected nodes**: Have at least one control edge (in or out). Emitted in control-wire traversal order.
2. **Independent unconnected nodes**: No control edges and no data inputs from control-connected nodes. Wrapped in a single `@dataflow:` block placed at the top of the output program.
3. **Dependent unconnected nodes**: No control edges but their data inputs come (transitively) from control-connected nodes. Wrapped in `@dataflow:` blocks placed immediately after the control node that satisfies all their data inputs, at the correct nesting depth.

This means `@dataflow:` blocks can appear:
- At the top level (for independent value nodes)
- Inside namespace bodies (for data nodes whose inputs are produced inside a loop or branch)
- At the top level after a control chain (for data nodes dependent on control-chain outputs)

#### Control-flow edges and `@dataflow:` blocks

Nodes inside a `@dataflow:` block have **no control edges between each other** — their ordering is determined purely by data dependencies and topological sort. However, the block as a whole has **boundary control edges** in the surrounding graph:

- **Entry boundary edge**: a ctrl edge from the last control-connected node before the block to the first node inside the block.
- **Exit boundary edge**: the last node inside the block continues the ctrl chain — the next control-connected node after the block receives a ctrl edge from it.

This boundary wiring means that a `@dataflow:` block appears as a logical segment in the control chain, even though its internal ordering is data-driven.

### 14.4 Branch/Switch/Merge/Parallel

- **Branch**: Emit `(cond)branch(\`true_label\`, \`false_label\`)`. Each ctrl output becomes a namespace containing the downstream control chain.
- **Switch**: Emit `(val)switch(case_val=>\`label\`, ...)`. Each ctrl output becomes a namespace.
- **Merge (post-branch)**: Code naturally converges after the namespace blocks end — no explicit statement needed.
- **Merge (loop entry)**: A merge node with an unconnected `entry` ctrl input marks the loop entry point. The compiler emits `()jump(\`ns_{merge_id}\`)` followed by a `ns_{merge_id}:` namespace containing the loop body. The backward edge (from branch `true` back to the merge) becomes `()jump(\`ns_{merge_id}\`)` inside the branch namespace.
- **Parallel**: Emit `()parallel(\`label1\`, \`label2\`, ...)` with a namespace per ctrl output.

The `@meta` for a merge node is attached to the `jump` statement that precedes the namespace, not to the namespace definition itself. This allows the decompiler to recover the merge node's position.

#### Merge node synthesis (graph extraction from KIR)

When extracting a `KirGraph` from a `.kir` source file (via `kir_to_graph`), the compiler does not emit explicit merge nodes in the text. Instead, merge nodes are **synthesized** in a post-processing step: after all control edges are resolved (including jump targets), any node that has two or more incoming ctrl edges gets a synthetic merge node inserted:

1. A new merge node is created with `in_0, in_1, ...` ctrl inputs (one per incoming edge) and a single `out` ctrl output.
2. All original edges pointing at the target are rewired to point at the respective `in_N` ports of the merge node.
3. A new ctrl edge is added from the merge node's `out` to the original target.

This synthesis accurately reflects the semantics of a loop entry point in the `.kirgraph` format, where the initial forward flow and the back-edge from the loop body both converge.

### 14.5 @meta Annotations

Each node emits `@meta node_id="..." pos=(x, y)` before its KIR statement. Additional `meta` fields on the node (e.g., `size`) are also included.

- **FuncCall / Branch / Switch / Parallel / Jump**: `@meta` is stored in the statement's `metadata` field.
- **Assignment** (Value nodes): `@meta` is also stored in the statement's `metadata` field. The `StripMetaPass` and decompiler both handle this correctly.

This enables full L2 → L1 decompilation from annotated KIR text.

---

## 15. L2 → L1 Decompilation Rules

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

---

## 16. Viewing and Layout

### 16.1 Graph Extraction from KIR Source

The `kir_to_graph(source: str) -> KirGraph` function extracts a `KirGraph` directly from `.kir` text without requiring the `{node_id}_{port}` naming convention. It tracks all variable definitions and usages at the AST level to wire data edges, and applies the boundary ctrl-edge rules for `@dataflow:` blocks and the merge-node synthesis described in Section 14.

This allows any `.kir` program — including hand-written files — to be visualized as a graph.

### 16.2 Auto-Layout

`auto_layout(graph: KirGraph) -> KirGraph` positions nodes that lack `meta.pos` using a Fischer-style BFS algorithm. See `docs/architecture.md` Section 7.2 for the full algorithm description.
