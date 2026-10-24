<h1 align="center">KohakuNodeIR</h1>
<p align="center">
  <strong>A text IR for node graphs: what an editor draws, a person reads, and a machine runs, as one program.</strong>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="License: Apache-2.0">
  <img src="https://img.shields.io/pypi/v/kohakunode" alt="PyPI version">
  <a href="https://github.com/KohakuBlueleaf/KohakuNodeIR"><img src="https://img.shields.io/github/stars/KohakuBlueleaf/KohakuNodeIR?style=social" alt="GitHub stars"></a>
</p>
<p align="center">
  <a href="docs/spec/README.md"><strong>Specification</strong></a> &nbsp;·&nbsp;
  <a href="docs/architecture.md"><strong>Architecture</strong></a> &nbsp;·&nbsp;
  <a href="examples/README.md"><strong>Examples</strong></a> &nbsp;·&nbsp;
  <a href="https://discord.gg/xWYrkyvJ2s"><strong>Discord</strong></a>
</p>

---

## Is this for you?

**You probably want KIR if** you build node-based tools (an image pipeline, an
agent workflow, a captioning graph) and want the graph to be a real program:
diffable text, loops and branches as explicit control flow, typed nodes from
signature files, a reference interpreter that defines the result, and an
executor that is free to run whatever the wires allow in parallel.

**You probably don't if** a plain DAG of tasks covers everything you need (a
workflow scheduler already does that well), or you want a general-purpose
scripting language. KIR has no expressions: every computation is a node, and
nodes are written in your host language.

## What KIR is

KIR describes **one job** as a node graph. Nodes are joined by two kinds of
wire: **control** wires ("then", top and bottom ports) and **data** wires
(values, side ports). The text is that graph written line by line:

```
(inputs)node(outputs)          a node; data wires are the names
label:                         a namespace, entered only by a builtin
(cond)branch(`yes`, `no`)      control flow is explicit: branch, switch, jump, parallel, each
@dataflow:                     a block ordered by data alone
@def (x: int)double(y: int):   a subgraph, called like any node
```

A complete program ([examples/tour/01_each.kir](examples/tour/01_each.kir)):

```
image = "photo"
boxes = [1, 2, 3, 4]
nodes = []
(boxes)each(box, i, `body`)
body:
    (box)is_new(fresh)
    (fresh)branch(`new_box`, `known_box`)
    new_box:
        (image, box)crop(c)
        (c)entity(node)
    known_box:
        node = None
    (nodes, node)append(nodes)
(nodes)summarize(summary)
```

**A job means its sequential run.** Statements run top to bottom, namespaces
are entered only by builtins, and a name holds the value last written to it.

**Parallel by default.** Nodes talk only through their wires, so an executor
may run any two nodes in either order or at once unless a data wire, the
control path, or a node flag (`mutates`, `ordered`) orders them. Nothing in a
program has to say what may run in parallel, the way a CPU issues several
instructions of one thread at once while the program order still defines the
result. `parallel` exists, but it states intent only.

**One language, many forms.** A program can be shown as a graph (for editors)
or as text (for people and tools). Optimization passes rewrite it into simpler
programs in the same language, down to a form an interpreter runs directly.
Nothing in the text marks which form it is in; every form is KIR, and every
form runs.

## Where it fits

|  | Graph is the program | Text form | Control flow | Typed nodes | Parallel by default |
|--|--|--|--|--|--|
| Node editor save files (e.g. ComfyUI workflow JSON) | yes | JSON only | no | per editor | executor-specific |
| Visual scripting (Blueprints, Scratch) | yes | no | yes | yes | no |
| Workflow DAGs (task schedulers) | yes | code or YAML | limited | no | yes |
| **KIR** | **yes** | **yes, line per node** | **yes, as wires** | **yes, signature files** | **yes** |

KIR sits between editors and executors. An editor (the example in
`apps/kir-editor`, a ComfyUI import, a Python builder, or a person with a text
editor) produces KIR; a machine receives KIR plus engines that implement its
nodes and never needs to know how the KIR was made.

## Key features

- **Text and graph are the same program.** `kir graph` / `kir text` convert
  both ways; canonical text survives the round trip byte for byte, and
  behaviour is always preserved.
- **Explicit control flow as wires.** `branch`, `switch`, `jump`, `parallel`,
  `each` and `@try` / `@except` each have a node shape, so loops and branches
  are visible in the graph, not hidden in node code.
- **Optimization passes over one language.** `order_dataflow`, `inline`,
  `expand_each`, `version`, `group`, `strip_meta`. Any prefix of the list is a
  valid program with the same behaviour; a tool picks the form it wants
  (`kir lower --passes ...`, `compile_source(..., passes=[...])`).
- **Signatures and `@use`.** Node libraries export `.kirsig.json` files
  (ports, types, defaults, flags), so the checker, editors and the language
  server never import node code. `@use "gbc" as g` makes a library callable.
- **Reusable source modules.** `@import "transforms.kir" as t` links explicitly
  exported KIR subgraphs before checking and lowering. Private definitions stay
  isolated; dependency manifests are portable across checkout locations. Structured
  origins retain definition and call-site ancestry through transformations
  ([modules and origins](docs/spec/modules.md)).
- **Typed records.** Signature schemas derive ordinary construction, field-read,
  and value-update nodes. Nominal immutable values isolate mutable containers;
  explicit codecs connect host representations without reflective properties
  ([record specification](docs/spec/records.md), [example](examples/records)).
- **A static checker.** Undefined reads on any path, wrong port counts, type
  mismatches, ambiguous names, bad labels, dataflow cycles: one code per rule
  ([checks.md](docs/spec/checks.md)).
- **Program hashes.** A semantic hash (ignores `@meta` and `@hint`) provides a
  program-identity component for executor cache/replay keys; a full hash also
  covers hints. Neither alone certifies implementation identity or equal results
  ([identity boundaries](docs/spec/execution-contract.md#identity-layers)).
- **Hints that never change results.** `@hint lane="vlm"` tells a scheduler
  something; deleting every hint leaves every result unchanged. Observable
  timeouts, retries, cancellation, and work limits are executor binding policy,
  not advisory hints. The [execution contract](docs/spec/execution-contract.md)
  distinguishes fixed-outcome replay from physical runs and warns about legacy
  Togeari `timeout_s` hint inference.
- **A reference interpreter with a call hook**, so a machine can replay its
  recorded node results and check that it computed what the program means.
- **Editing support.** A tree-sitter grammar, a VS Code extension, and a
  language server (`kir-lsp`: diagnostics, hover, completion, go-to-definition,
  formatting).
- **ComfyUI import / export.** Both the UI workflow and the API prompt.
- **A Rust core** (PyO3 module and WASM build) that reproduces the Python
  reference byte for byte on the shared golden corpus.

## Quick start

> **Python** 3.11 or newer. At run time `kohakunode` depends only on `lark`.

### 1. Install

```bash
pip install kohakunode                 # the Python reference, the Rust core (kohakunode._rs), `kir`
pip install "kohakunode[lsp]"          # plus the language server `kir-lsp`
```

From source (builds the Rust core, so a Rust toolchain is needed):

```bash
git clone https://github.com/KohakuBlueleaf/KohakuNodeIR.git
cd KohakuNodeIR
pip install -e ".[dev]"                # pytest, ruff, black, pygls, maturin
```

### 2. Write nodes

```python
# my_nodes.py
from kohakunode import NodeLibrary

lib = NodeLibrary("my_nodes")

@lib.node(outputs=["sum"])
def add(a: int, b: int) -> int:
    return a + b

@lib.node(outputs=["graph"], mutates=["graph"])   # changes its input in place
def attach(graph: list, node: str) -> list:
    graph.append(node)
    return graph

@lib.node(ordered=True)                             # touches the outside world
def log(message: str) -> None:
    print(message)
```

A node may depend only on its inputs and affect the job only through its
outputs; the two flags declare the exceptions once, in the registry
([writing nodes](docs/guides/writing-nodes.md)).

### 3. Export signatures for tools that should not import your code

```bash
kir sig export my_nodes -o sigs/       # writes sigs/my_nodes.kirsig.json
```

Programs then say `@use "my_nodes"`; the tools find the file on `--sig-path`
or `KIR_SIG_PATH`.

### 4. Use the toolchain

```bash
kir check prog.kir --lib my_nodes            # diagnostics with codes (checks.md)
kir fmt prog.kir -w                          # canonical text, in place
kir lower prog.kir --lib my_nodes            # after every pass
kir lower prog.kir --passes order_dataflow,inline --hash
kir graph prog.kir -o prog.kirgraph          # text -> graph view (--data variables: values through get/set, graph IO wired direct)
kir text prog.kirgraph                       # graph view -> canonical text (--no-meta to drop ids/positions)
kir run prog.kir --lib my_nodes              # the reference run; prints final values
kir-lsp                                      # language server on stdio
```

`--lib` imports a Python module that defines a `NodeLibrary`; `--sig-path`
adds directories of signature files.

## Core mental model

### Two kinds of wire

```text
            control in
               |
      +--------v--------+
 a -->|                 |--> sum         data wires: values, by name
 b -->|   (a, b)add     |
      +--------+--------+
               |
            control out                  control wires: "then"
```

A call node has control ports on top and bottom and data ports on its sides.
`branch` has one control output per label, `merge` joins control paths (a
labelled merge is a loop entry), `each` has `body` / `done` outputs and a
`next` input its body returns to. The full list of node kinds and ports is in
[graph.md](docs/spec/graph.md).

### Namespaces and continuation

```
(is_big)branch(`big`, `small`)
big:
    (x)shrink(x)
small:
    (x)grow(x)
(x)log()              # both paths continue here, after the namespace definitions
```

A namespace is skipped when reached in sequence and entered only by a builtin.
When its body ends, execution continues after the namespace's definition; an
`each` body returns to its `each`; `parallel` arms run one after another;
`@dataflow:` and `@try` bodies continue after their statement. `jump` is the
only way back, so a loop is a namespace entered by a `jump` from before it and
re-entered by a `jump` from inside it.

### The pass pipeline

```text
 .kirgraph (editor) <-> canonical .kir text
                             |
                         check (E/W codes)
                             |
  order_dataflow -> inline -> expand_each -> version -> group -> strip_meta
       (every intermediate program is valid KIR and runs)
                             |
          +------------------+------------------+
          |                                     |
 reference interpreter                  machines (parallel,
 (sequential, defines the result)       as if sequential)
```

After every pass, each `@dataflow:` block is a straight run whose dependence
graph a machine computes once: every write has its own version `x__n`, and a
name written on several paths gets a home version `x__0`. Control statements
between blocks choose what runs next; a job's state is its position plus its
values ([passes.md](docs/spec/passes.md)).

## Toolchain

| Piece | Where | What |
|---|---|---|
| Python reference | `src/kohakunode/` | parser, writer, checker, passes, hashes, graph view, interpreter, CLI, ComfyUI, language server; the ground truth |
| Rust core | `rust/` | the same parse, write, check, passes, hashes and graph conversion; shipped in the wheel as `kohakunode._rs`, plus a WASM build |
| tree-sitter grammar | `editors/tree-sitter-kir/` | highlighting and structure for any tree-sitter editor |
| VS Code extension | `editors/vscode/` | highlighting, snippets, folding, and a client for `kir-lsp` |
| Example node editor | `apps/kir-editor/` | Vue 3 + Vue Flow + elkjs + CodeMirror: nodes, flowchart, sequence, blocks and text views of one program |

### Rust core

```bash
maturin develop --release                   # from the repo root: kohakunode with kohakunode._rs, into the active venv
python rust/tests/parity/parity.py          # the Rust core against the Python reference
cd rust && cargo test                       # unit tests + golden corpus, byte for byte

# WASM for browsers
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.129   # must match wasm-bindgen in Cargo.lock
cargo build --release --target wasm32-unknown-unknown --features wasm
wasm-bindgen --target web --out-dir pkg target/wasm32-unknown-unknown/release/kohakunode_rs.wasm
```

`kohakunode._rs` takes and returns text: `format`, `parse_to_json`, `check`,
`lower(passes=None)`, `hashes`, `to_graph`, `from_graph`, `std_signatures`;
signatures come as `.kirsig.json` texts and, for `check` / `lower` / `hashes` /
`to_graph`, through `base=` and `sig_path=` the way `@use` resolves them. The
WASM build exposes the same functions to browsers (signature texts only). `\N{...}` string escapes use the default
`unicode-names` feature; `--no-default-features --features wasm` builds a
smaller WASM file without it.

### VS Code

```bash
pip install -e ".[lsp]"
cd editors/vscode && npm install
ln -s "$(pwd)" ~/.vscode/extensions/kir-language
```

Settings `kir.server.path`, `kir.server.args` and `kir.sigPath` choose the
server command and the signature directories ([editors/vscode](editors/vscode/README.md)).

### Example node editor

```bash
pip install fastapi uvicorn
cd apps/kir-editor/backend && python -m uvicorn kir_editor.app:app --port 48888
cd apps/kir-editor/frontend && npm install && npm run dev     # http://localhost:5173
```

Five views of one program: nodes (ComfyUI / Blender / UE style, with data as
variables or wires and control as exec wires or frames), a classic ROBO Pro
flowchart, an EV3-style sequence, Scratch blocks, and text; any two side by
side. A palette built from signature files, an inspector, undo / redo, and
Problems / Run / Lowered panels with per-pass toggles
([apps/kir-editor](apps/kir-editor/README.md)).

## Python API

```python
from kohakunode import (
    parse, write,                  # text <-> AST; parse(write(p)) == p
    check,                         # diagnostics
    compile_source, compile_file,  # env + check + passes + hashes in one call
    Interpreter,                   # the sequential reference run, with a call hook
    NodeLibrary,                   # the node registry
)
from kohakunode.graph import to_graph, from_graph          # graph view
from kohakunode.comfyui import from_comfyui, to_api        # ComfyUI
from kohakunode.lower import PASSES, run_passes            # individual passes

compiled = compile_source(text, [lib], passes=["order_dataflow", "expand_each"])
compiled.program         # the checked program as written
compiled.lowered         # after the chosen passes (all of them when passes=None)
compiled.diagnostics     # warnings; errors raise KirCheckError
compiled.semantic_hash, compiled.full_hash

graph = to_graph(compiled.program, compiled.env)   # .kirgraph dict
text = write(from_graph(graph, with_meta=False))   # canonical text

def replay(name, inputs, call):                    # a machine's recorded results
    return recorded[(name, key(inputs))]

Interpreter(compiled.lowered, compiled.env, hook=replay).run()
```

## Codebase map

```text
src/kohakunode/
  syntax/      kir.lark grammar, parser, AST, canonical writer
  sig/         NodeLibrary, .kirsig.json files, @use resolution, types, kir.std
  flow/        control-flow graph, reaching definitions, dataflow ordering
  check/       every rule of docs/spec/checks.md
  lower/       the optimization passes and program hashes
  run/         the sequential reference interpreter
  graph/       text <-> graph view
  comfyui/     ComfyUI workflow / API prompt import and export
  lsp/         the language server (kir-lsp)
  cli/         the kir command
  compiler.py  compile_source / compile_program / compile_file
rust/          the Rust core, PyO3 and WASM bindings
editors/       tree-sitter-kir, vscode
apps/          kir-editor (example node editor)
examples/      basics (v1 programs), tour (one file per feature), gbc, comfyui
tests/         unit tests, the v1 reference corpus, the golden corpus
docs/          spec/, guides/, architecture.md, plan/
```

## Documentation map

### Specification
[Overview](docs/spec/README.md) · [Language](docs/spec/language.md) · [Semantics](docs/spec/semantics.md) · [Signatures and `@use`](docs/spec/signatures.md) · [Graph view](docs/spec/graph.md) · [Optimization passes](docs/spec/passes.md) · [Checks](docs/spec/checks.md)

### Guides
[Writing nodes](docs/guides/writing-nodes.md) · [Running KIR on a machine](docs/guides/machines.md) · [Examples](examples/README.md)

### Internals
[Architecture](docs/architecture.md) · [v2 work plan](docs/plan/v2.md)

## Testing

```bash
pytest                                   # the Python reference: unit tests, golden corpus, v1 parity, generated programs
cd rust && cargo test                    # the Rust core against the same golden corpus
cd apps/kir-editor/frontend && npm run test:e2e   # one browser smoke run of the example editor
```

The golden corpus (`tests/corpus/golden`) holds the canonical text, the fully
optimized text, the graph view and the hashes of every case; the Python
reference and the Rust core must both reproduce it byte for byte. The v1
corpus (`tests/corpus/v1`) records what the v1 implementation printed for
every v1 program; v2 reproduces it except for listed, deliberate differences.

## Releases

`kohakunode` is one wheel: the Python reference plus the Rust core as the
extension module `kohakunode._rs`. The version is `rust/Cargo.toml`'s
(`pyproject.toml` reads it dynamically). Publishing a GitHub release, or
pushing a `v*` tag, runs `release.yml`: wheels for CPython 3.11–3.14 on Linux
x86_64 / aarch64 (manylinux 2_28), Windows x64 and macOS arm64, Android wheels
(arm64, x86_64; Python 3.13) and the sdist, all uploaded to PyPI and to the
GitHub release.

## Coming from v1

v2 keeps v1's model (sequential meaning, namespaces entered by builtins,
`jump` loops, `@dataflow:`, `@def`) and every program v1 parsed still parses. New:
`@use`, `each`, `@try` / `@except err`, typed `@def` parameters and outputs,
`@hint`, node flags, the graph view with control ports, and optimization
passes in place of fixed levels. The v1 implementation is in the git history
(commit `1abda17`).

## License

[Apache-2.0](LICENSE)

Copyright 2026 Shih-Ying Yeh (KohakuBlueLeaf) and contributors.

## Community

- Discord: https://discord.gg/xWYrkyvJ2s
- Issues: https://github.com/KohakuBlueleaf/KohakuNodeIR/issues

## FAQ

**Does a program have to say what runs in parallel?**
No. A job means its sequential run, and an executor may overlap anything the
wires, the control path and node flags allow. `parallel` states intent only.

**Why is there no expression syntax?**
Every computation is a node, so the graph and the text stay the same thing.
`kir.std` provides the small pure nodes most programs need (`add`, `less`,
`len`, `append`, `to_str`, ...).

**What does an executor need besides the text?**
Implementations of the nodes the program calls. Signature files describe them
to tools; executors map node names to implementations themselves.

**How do I know a machine computed the right thing?**
Run sample jobs on the machine and on the reference interpreter with a call
hook that replays the machine's node results, then compare final values
([machines.md](docs/guides/machines.md)).

**Which pass output should a machine run?**
Its choice. The fully optimized program is the simplest to schedule; a machine
that schedules `each` itself can stop before `expand_each`. Every form means
the same thing.
