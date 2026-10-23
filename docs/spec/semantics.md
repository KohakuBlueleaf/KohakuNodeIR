# Semantics

## A job means its sequential run

A program's meaning is what the sequential interpreter does with it:
statements run top to bottom, namespaces are entered only by builtins, and a
name holds the value last written to it.

## Parallel by default

Nodes communicate only through their wires: a node's behaviour depends on its
inputs, and its effect on the job is its outputs. Therefore an executor may run
any two nodes in either order, or at once, unless one of these orders them:

1. **Data**: a node reads a value another node writes. Every write is its own
   version (passes.md, `version`), so reusing a name never orders anything.
2. **Control**: a node runs only on the path its branches select, so it waits
   for the conditions on that path. Nodes after a merge that read nothing
   written on the merged paths do not wait for those conditions.
3. **Node flags** declared in the node's signature (below).

No program text is needed to allow parallel execution, and nothing in a
program can require it. `parallel` states intent only.

This is the same contract a CPU keeps when it issues several instructions of
one thread at once: the program order defines the result, the hardware is free
to reorder whatever the result cannot tell apart.

## Node flags

Set by a node's author in its signature (signatures.md), never in programs.

- **`mutates: [input, ...]`**: the node changes these inputs in place. An
  executor must finish every earlier reader of the version being changed
  first, or hand the node a copy.
- **`ordered: true`**: the node touches state outside its wires (a file, a
  service). Ordered nodes of one job run in program order. Their results are
  never replayed from a cache.

A node without flags must not change its inputs. Debug executors may
fingerprint inputs before and after a call and fail a node that changed one it
did not declare.

## Names and scopes

- The top level of a file and each `@def` body are separate scopes. A `@def`
  body sees only its parameters and the names it writes; its outputs are the
  final values of the output names.
- Within a scope, names are flat: namespaces do not create scopes.
- A name read at a point must be written on every path reaching that point
  (checks.md).

## Namespaces

1. A namespace is skipped when reached in sequence.
2. It is entered only by `branch`, `switch`, `jump`, `parallel` or `each`. The
   label must name a namespace in the current block or, for `jump`, in an
   enclosing block.
3. When a namespace's body ends, execution continues at the statement after
   the namespace definition in the enclosing block, except for an `each` body
   (below).
4. `jump` leaves every block between the current one and the target's block.
   It is the only way to loop back; a loop is a namespace entered by a `jump`
   from before it and re-entered by a `jump` from inside it.

## Builtins

- **`branch`**: the condition must be a `bool`.
- **`switch`**: compares with `==` against each case in order; `_` matches
  anything. No match and no default is a runtime error.
- **`parallel`**: enters each label once, in any order; continues after all
  have finished. The reference interpreter enters them in the listed order.
- **`each`**: evaluates `items` once. For each element, in order, binds the
  element (and the index) and enters the body; when the body ends, control
  returns to `each` for the next element. After the last element (or none),
  execution continues after the body's namespace. A `jump` out of the body
  ends the loop.
- **`collect`**: snapshots the finite input and executes its body like `each`,
  reading one yielded expression at each normal body completion. Results are a
  fresh list in input order, assigned only after complete success. Carried state
  and prior writes/effects retain sequential meaning. Escaping jumps and target
  references inside the body are rejected. Initially, programs containing this
  construct cannot call declared `mutates` nodes, to avoid unsafe container aliases.
  See [collect.md](collect.md) for precise failure and lowering behavior.

## Subgraphs

A `@def` call binds the arguments to the parameters (defaults fill missing
ones), runs the body in its own scope, and returns its output names' values. A
`@def` may call other `@def`s but not itself, directly or indirectly.

## Errors

```
@try:
    try_body
@except err:
    except_body
```

If a node in `try_body` raises, the job continues with `except_body`. Writes by
statements before the failing one, in program order, stand; writes by
statements after it are discarded. With a name after `@except`, that name is
bound to the error value: a dict with `kind` (exception type name), `node`
(node name) and `message`. An error outside any `@try` fails the job.

An executor that runs `try_body` nodes in parallel must give the same result:
on failure it cancels the region's pending work where it can and discards the
results of statements after the failing one.

## Committed events

The standard ordered call `emit(topic, payload)` contributes one portable,
immutable event to the job's semantic event sequence after successful logical
call completion. It has no outputs and no special syntax. Equal payloads from
distinct invocations remain distinct events. Earlier committed events survive
later failures; `@try` does not roll them back. Speculative or squashed younger
calls must not publish events. Reference event delivery failure occurs after
commitment and is a fatal `EventDeliveryError`, not a catchable node failure.
See [events.md](events.md) for exact standard-node identity, payload capture,
call-hook replay, and the executor transport boundary.

## Hints and metadata

`@meta` and `@hint` never change results. Deleting all of them leaves every
job's result unchanged. `@meta` is for editors and the `strip_meta` pass
removes it; `@hint` survives every pass for executors. KIR does not interpret
hint keys.

Observable timeout, retry, cancellation, and step/work-budget behavior belongs
to an executor's binding policy, not to advisory hints. A binding may expose a
failure that selects an ordinary KIR handler; this does not give a hint key
source-level semantics. The reference defines behavior for supplied node
outcomes, not elapsed-time deadlines. See [execution-contract.md](execution-contract.md)
for fixed-outcome replay, resource-limit boundaries, and the explicit warning
about legacy Togeari `timeout_s` hint inference.

## Literals and values

Values are opaque to KIR except where the language looks at them: `branch`
conditions (`bool`), `switch` cases (`==`), `each` items (iterable, evaluated
once into a list).
