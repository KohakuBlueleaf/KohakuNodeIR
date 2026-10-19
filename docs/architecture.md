# Architecture

```
 editor (.kirgraph view) ──to/from──▶ .kir text ──check──▶ passes ──▶ optimized .kir text
                                         ▲                               │
                     Python builder / people / ComfyUI import            ├──▶ reference interpreter (sequential)
                                                                         └──▶ machines (parallel, as if sequential)
```

## Python reference (`src/kohakunode/`)

| Package | Role |
|---|---|
| `syntax/` | `kir.lark` grammar, parser to the AST (`ast.py`), canonical writer. `parse(write(p)) == p`. |
| `sig/` | Node signatures and libraries: `NodeLibrary` (decorator registry), `.kirsig.json` files, `@use` resolution (`env.py`), type syntax and compatibility, `kir.std` and the internal `kir.` nodes. |
| `flow/` | The control-flow graph of a scope (namespaces, builtins, `@try` exception edges, `each` bind nodes) and reaching definitions; stable topological ordering of `@dataflow:` blocks. |
| `check/` | Every rule of `docs/spec/checks.md`, as `Diagnostic(code, message, line)`. |
| `lower/` | The optimization passes (program → program): order `@dataflow:`, inline `@def`, expand `each`, version names, group straight runs, strip `@meta`; the semantic and full hashes. |
| `run/` | The sequential reference interpreter, with a call hook for executors (replay, logging). |
| `graph/` | Text → graph view (`to_graph`) and graph view → canonical text (`from_graph`). |
| `comfyui/` | ComfyUI UI workflow / API prompt import, API export. |
| `cli/` | The `kir` command. |
| `compiler.py` | `compile_source` / `compile_program`: env, check, lower, hashes in one call. |

Python is the ground truth. The Rust core (`rust/`) reproduces parse, write,
check, lower, hashes and graph conversion byte for byte, for the PyO3 module
and the browser (WASM); `tests/corpus/golden/` is the shared reference.

## Control flow, statically

Where a block continues after it ends is fixed by what contains it: a namespace
entered by `each` returns to the `each`; a `parallel` arm continues with the
next arm (the last with the statement after the `parallel`); any other
namespace continues after its own definition; `@dataflow:` and `@try` bodies
continue after their statement. The CFG builder and the interpreter implement
the same rule, so the checker, the lowering and the run agree.

## Versions

The `version` pass gives every write its own version `x__n`. A read reached by exactly
one write reads that version. A name read where several writes may reach
(after a branch, around a loop, after a failing `@try`) gets a home version
`x__0`: every write of it is followed by a copy into `x__0`, and those reads
read `x__0`. A machine scheduling one `@dataflow:` block therefore sees exact
dependences for single-write names and a flat variable for the rest, which it
renames as it runs.

## Tests

`tests/` holds the cheap checks only:

- `test_v1_parity.py`: every v1 program v1 ran cleanly gives the same stdout
  and final values under v2 (the fully optimized program on the reference
  interpreter), except the listed, deliberate differences.
- `test_golden.py`: canonical text, optimized text, graph view and hashes equal
  `tests/corpus/golden`.
- `test_graph.py`: graph → text → graph is a fixed point and keeps behaviour.
- `test_generated.py`: 150 seeded random programs (`progen.py`): every prefix
  of the pass list runs exactly like the source, re-sorting the optimized
  program changes nothing, and the graph round trip keeps behaviour and is a
  fixed point.
- `test_pipeline.py`, `test_syntax.py`, `test_tools.py`, `test_examples.py`:
  one test per feature and one wrong program per checker rule.
