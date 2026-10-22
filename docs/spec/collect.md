# Result-producing finite iteration

`collect` executes a body for each item and publishes its results in input order.
It is explicit control flow, not an opaque host graph-interpreter node.

```text
([1, 2, 3])collect(item, index, `body`, value -> results)
body:
    (item, 2)mul(value)
```

The index is optional: ``(items)collect(item, `body`, value -> results)`` (with the
body label written in backticks). Item/index may use `_` to discard bindings.
The final pair is special: its value expression (name or literal) is read at
**normal body completion**, not on entry. Its target is a name.

`collect` is now an unqualified control-builtin name. Older host nodes named
`collect` remain available through an explicit library alias, for example
`@use "host" as h` followed by `(items)h.collect(result)`. Rename a same-file
`@def collect` before using the new language version; qualified host calls are not
interpreted as this builtin. Other existing `each` and host calls are unchanged.

## Sequential meaning

1. Evaluate the input once and eagerly snapshot its finite iterable, as for `each`.
2. Bind item/index and execute the body in input order in the reference.
3. At normal body completion, read the yielded expression once and retain one value.
4. After every iteration succeeds, assign a fresh list to the target.
5. Empty input assigns a fresh empty list without executing the body.

Results follow input order regardless of engine completion order. The target has
`list[T]` type when the yielded type is known, otherwise an unknown element type.
Empty input does not erase the statically inferred element type.

Namespaces retain the existing flat enclosing scope. Ordinary body writes and
item/index bindings have the same visibility/carried dependencies as `each`.
Iterations need not be independent:

```text
total = 0
([1, 2, 3])collect(item, `body`, total -> totals)
body:
    (total, item)add(total)
```

The result is `[1, 3, 6]`; the carried dependency remains ordered. The yielded name
must be defined on every path to body completion. A value defined before the
collection may intentionally be reused; a fresh write each iteration is not
mandatory. No tree reduction or reassociation is implied.

The collector is private. The target cannot be read or written inside its body,
used as an item/index binding, or used as its own yielded input. Partial results
cannot be observed.

## Failure, effects, and control

An escaping body failure abandons the collection. The target retains its previous
binding, or remains undefined if none existed. Ordinary writes and ordered effects
before the failure in program order stand, including earlier statements of the
failing iteration. Younger speculative work is discarded under normal precise
fault rules. The first relevant failure is taken in program order, not completion
order.

Input snapshot failure is catchable under `@try` with the original exception kind
and message and semantic node name `kir.collect_items`. No body iteration or target
assignment occurs. Direct/native collection computes this control operation without
a user call hook; the expanded baseline calls the same reserved helper explicitly.
Ordinary `each` input-error behavior is unchanged.

A handler inside the body may recover and reach normal completion; the iteration
then contributes one value. An outside handler sees the abandoned collection, not
a published partial list. Branches, switches, internal loops, and nested collections
are supported.

Explicit jumps leaving the body are rejected. External jumps into it are also
rejected, as for `each`. Internal jumps remain legal. This restriction concerns
explicit control transfers, not exception propagation. There is no implicit
break/partial-prefix result contract.

## Initial alias safety restriction

The list retains yielded references; it does not deep-copy opaque host values.
Under node contracts without input mutation, these values remain stable while the
collector builds its result.

Initially, **any program containing `collect` rejects all resolved host calls with
a nonempty `mutates` declaration**, including calls in definitions, callers, and
code outside the body. Linking precedes the check. This conservative whole-program
restriction avoids claiming container-alias tracking the speculative mutation
mechanism does not provide. Existing each-only programs are unchanged.

Assignments, fresh-list append, immutable record updates, and `ordered` nodes
without input mutation remain allowed. An ordered node changing an input must
declare `mutates` and is rejected. Undeclared mutation, background mutation of
returned values, and outside mutation of admitted inputs remain contract violations.

This explicit limit does not silently deep-copy results or rewrite arbitrary append
loops. Relaxation requires a separately validated alias model.

## Graph and compiler

`Collect` is a distinct control AST node. Entry reads only the iterable; a synthetic
body-end sample reads the yielded value, and successful completion writes the target.
Reaching definitions and checking model these distinct points. The graph has
body/next/done control ports and a `value` data input tagged
`deferred: "body_end"`, never an eager DAG dependency. Item/index and final results
are visible outputs.

The correctness-first `expand_collect` pass lowers to existing iteration, a private
hygienic list accumulator, `kir.collect_items` input snapshot, and reserved pure
`kir.collect_append`. The append helper has
fresh-list append semantics immune to host-library shadowing. Only successful
completion assigns the target. Generated init/append/result operations retain
structured origins.

```text
order_dataflow -> expand_collect -> inline -> expand_each -> version -> group -> strip_meta
```

Executors supporting native collection may omit `expand_collect`. Passes requiring
expanded iteration reject a remaining collection instead of losing it. Existing
custom pass lists without collection preserve their behavior. The lowering is an
inspectable correctness baseline: fresh-list append copies quadratically many
references; native collection can retain results and finalize in linear work.

## Runtime and replay

Togeari's normal passes retain collection control. Each dynamic invocation owns a
private collector. Body calls remain ordinary engine calls. Capture waits for its
yielded value and commits in logical order, not when a strand ends fetching.
Output publication occurs after all successful captures retire. Nested collectors
have distinct state.

Explicit `expand_collect` execution replays the correspondingly collection-expanded
reference form, retaining definitions, so helper calls match the fallback trace.
Native replay uses the authored construct and records ordinary body calls only.
Origin metadata is never used to guess administrative-call semantics.

Snapshots are initially unavailable while a native collector is active; ordinary
snapshotting can resume after completion. Requested checkpoint progress through
collectors belongs to the reliable-checkpoint increment. Collection remains finite
and eager, not an incremental value stream.
