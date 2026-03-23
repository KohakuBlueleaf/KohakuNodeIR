# Kohaku Node IR - Language Specification

**Version**: 0.1.0-draft

## 1. Overview

Kohaku Node IR (`.kir`) is an intermediate representation language designed for node-based visual programming systems. It serves as middleware between node UI frontends and backend execution engines, allowing different node UI designs to share the same backend.

The language supports both:
- **Control-flow** visual programming (Scratch, Lego Mindstorms, Fischer Technik)
- **Data-flow** visual programming (ComfyUI, Blender node editor)

### 1.1 Three-Level IR Architecture

KohakuNodeIR uses a three-level intermediate representation:

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

Level 2 (`.kir`) is the **pivot format** — it can convert to both L1 (for UI) and L3 (for execution). The `.kirgraph` format specification is in `kirgraph_spec.md`.

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

**Example — mixing control flow and dataflow:**

```
# Dataflow section: initialization (order resolved by deps)
@dataflow:
    (10)to_float(limit)
    (0)to_float(counter)

# Control flow section: explicit loop
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep)
    (keep)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:

# Dataflow section: post-processing
@dataflow:
    (counter)to_string(s)
    ("Counted to: ", s)concat(msg)
    (msg)print()
```

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
