# Optimization passes

There is one language. A program can be shown as a graph (`.kirgraph`, for
editors) or as text, and it can be rewritten by optimization passes. Each pass
takes a KIR program and returns a simpler KIR program with the same meaning,
so the program after any number of passes is still valid KIR and runs on the
interpreter. Running every pass gives the most directly interpretable form:
no `@def`, no `each` or `collect`, every name versioned, straight runs grouped. Which form
a tool uses is its own choice; nothing in the text marks it.

Passes run in this order; a pass may need earlier ones, as listed. Every name
or label a pass creates contains `__`, which programs may not use. Passes run
only on programs that pass the checker (checks.md).

| Pass | Needs | Does |
|---|---|---|
| `order_dataflow` | — | order each `@dataflow:` block by data; apply `@mode dataflow` |
| `expand_collect` | — | lower ordered collection to private accumulation and `each` |
| `inline` | `order_dataflow` | replace `@def` calls by renamed copies of their bodies |
| `expand_each` | — | rewrite `each` as a loop of builtins and internal nodes |
| `version` | `order_dataflow`, `inline`, `expand_each` | one version per write; home versions at merges |
| `group` | — | wrap straight runs in `@dataflow:` blocks |
| `strip_meta` | — | drop `@meta` (editor data) |

## `order_dataflow`

Statements of each `@dataflow:` block (and of a `@mode dataflow` file) are put
in stable topological order: a statement comes after every other statement of
the block that writes a name it reads, and whenever several are ready the one
earliest in the text goes first. Nodes flagged `ordered` keep their text order
among themselves. A cycle is an error (`E033`). The `@mode` line is dropped.

Interpreters apply the same ordering when they run a program, so this pass
changes nothing about what the program does.

## `expand_collect`

Each collection receives a hygienic private accumulator. `kir.collect_items`
snapshots the input; `each` executes the body; `kir.collect_append` appends its
body-end result by returning a fresh list; a final assignment publishes the user
target only on successful completion. Both helpers are reserved deterministic
internal nodes, not calls that host-library shadowing can change. Origins mark
items/init/append/result operations. The direct reference and native runtime may
use private linear accumulation instead of the quadratic copying baseline.

`expand_collect` normally precedes `inline`, but supports already-inlined bodies.
`expand_each` and `version` reject a remaining collection; custom pass sequences
without collections retain their existing requirements. See [collect.md](collect.md)
for control, exception, alias restrictions and replay behavior.

## `inline`

Each `@def` call is replaced by a copy of the body. In copy number `k` of
subgraph `name`, every name and label `x` becomes `name__k__x`; parameters are
bound by assignments before the copy and outputs by assignments after it.
Copies are numbered in order of appearance, after inlining their callers. The
`@def` blocks are then removed.

## `expand_each`

```
(items)each(x, i, `body`)
body:
    S
```

becomes, with `k` numbering the `each` statements in order of appearance:

```
(items)kir.to_list(each__k__items)
each__k__index = 0
()jump(`each__k`)
each__k:
    (each__k__items, each__k__index)kir.item_at(each__k__item, each__k__more)
    (each__k__more)branch(`body`, `each__k__done`)
    body:
        x = each__k__item
        i = each__k__index
        S
        (each__k__index)kir.next_index(each__k__index)
        ()jump(`each__k`)
    each__k__done:
```

Without an index output the `i = ...` line is left out; a `_` item leaves out
the `x = ...` line. After the loop, `x` and `i` hold the last element and its
index, as after a Python `for`. `kir.to_list`, `kir.item_at` and
`kir.next_index` are internal nodes every executor provides: `to_list` copies
an iterable into a list, `item_at` returns the element at the index (or
`None`) and whether the index is in range, `next_index` adds one.

## `version`

On the control-flow graph of the program (sequence, namespace entry and end,
`jump`, and from every statement of a `@try` body to its handler):

- Every write of name `x` becomes a write of a fresh version `x__n`, numbered
  per name in order of appearance.
- A read reached by exactly one write reads that write's version.
- A name read somewhere with several writes reaching it (after a branch,
  around a loop, after a failing `@try`) gets a home version `x__0`: every
  write of it is followed at once by `x__0 = x__n`, and those reads read
  `x__0`. The home version is the flat name, so it is right on every path.
- `parallel` arms are versioned in listed order.

## `group`

Every straight run of calls and assignments becomes a `@dataflow:` block,
statements in program order. A run is split before a statement that writes a
name an earlier statement of the run reads (a home version read at a loop's
top and written back at its end). So no block reads a name a later statement
of it writes, and ordering it by data gives back its text order: the grouped
program means the same whether or not anyone sorts it again.

## `strip_meta`

`@meta` lines are removed; `@use`, `@typehint` and `@hint` stay.

## The fully optimized form

- A machine computes the dependency graph of each `@dataflow:` block once: a
  statement depends on the last earlier statement in the block that writes a
  name it reads, plus node flags; names written more than once (home versions)
  also order by earlier readers and writers unless the machine renames values
  as it runs. Control statements between blocks choose what runs next. A job's
  state is its position plus the values of its versions.
- The source name of a version is the name with its `__<digits>` suffix
  removed. The reference interpreter reports, for every source name of the top
  level, the value of the version written last in execution order; this equals
  the value a run of the program as written leaves in that name.

## Program hashes

The low-level `semantic_hash(program)` and `full_hash(program)` identify the
supplied representation, usually the fully optimized one:

- **Semantic hash**: SHA-256 of the canonical text without `@meta` and `@hint`.
- **Full hash**: SHA-256 of the canonical text without `@meta`. It also
  identifies the hints, for run reports.

These helpers do not resolve external dependencies. `Compiled.semantic_hash`
and `Compiled.full_hash` additionally mix the dependency manifest for source
modules and record-bearing programs, including resolved signature contracts
([modules.md](modules.md#dependency-identity)). Legacy compilation without those
features retains its previous hash construction.

Equal program hashes alone do not certify equal results: inputs, resolved
contracts, implementation behavior, and exposed outcomes must also correspond.
The sequential reference defines the result under the same inputs, resolved
contracts, and supported matched outcomes, with the execution-limit qualifications
in [execution-contract.md](execution-contract.md). A program hash is a component
of executor cache/replay identity, not a fingerprint of arbitrary implementations
or a complete execution manifest. Conversely, semantics-preserving passes can
change the representation hash without changing behavior.
