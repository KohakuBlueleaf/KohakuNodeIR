# Kohaku Node IR - Language Specification

**Version**: 0.1.0-draft

## 1. Overview

Kohaku Node IR (`.kir`) is an intermediate representation language designed for node-based visual programming systems. It serves as middleware between node UI frontends and backend execution engines, allowing different node UI designs to share the same backend.

The language supports both:
- **Control-flow** visual programming (Scratch, Lego Mindstorms, Fischer Technik)
- **Data-flow** visual programming (ComfyUI, Blender node editor)

### 1.1 Design Principles

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

A namespace is a labeled, indented block. See [Section 4: Execution Model](#4-execution-model) for semantics.

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

**Rule 4 — No implicit upward escape**: Code inside a child namespace cannot reach the parent scope without an explicit `jump`. But when the child block ends naturally, execution automatically continues in the parent.

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

## 5. Dataflow Mode

```
@mode dataflow
```

When declared at the top of a file, this signals that:
1. The IR was emitted by a data-flow UI
2. Line order is a **hint** but not the authoritative execution order
3. The backend **MUST** compile this IR into standard sequential KohakuNodeIR before execution

The compilation step involves:
- Analyzing data dependencies (which inputs reference which outputs)
- Producing a valid topological ordering
- Emitting standard sequential IR

After compilation, the result is executed using the standard sequential model. Dataflow mode is purely a convenience for data-flow UIs that don't want to perform topological sorting themselves.

**Constraint**: Dataflow mode files must NOT contain control-flow constructs (`branch`, `switch`, `jump`, namespaces). If control flow is needed, the UI must compile to standard sequential IR directly.

---

## 6. Grammar Summary (EBNF-style)

```
program        = { statement }
statement      = assignment | func_call | namespace_def | meta_anno | subgraph_def | mode_decl | comment

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
mode_decl      = "@mode" IDENT

literal        = INT | FLOAT | STRING | BOOL | NONE | list_lit | dict_lit
list_lit       = "[" [ expression { "," expression } ] "]"
dict_lit       = "{" [ dict_pair { "," dict_pair } ] "}"
dict_pair      = expression ":" expression

FUNC_IDENT     = IDENT { "." IDENT }
```

---

## 7. Reserved Words and Symbols

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

## 8. Conformance

### 8.1 Backend Requirements

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

### 8.2 UI Requirements

A conforming UI MUST:
1. Emit valid `.kir` syntax
2. Preserve round-trip fidelity: loading and re-saving a `.kir` file should not lose information

A conforming UI MAY:
1. Emit `@mode dataflow` and rely on the backend for topological sorting
2. Emit additional `@meta` fields for UI-specific layout data
