# Explicit ordered collection

Run from the repository root with the current checkout installed. No host library
or service is needed:

```sh
python examples/collect/run.py
kir check examples/collect/main.kir
kir run examples/collect/main.kir
kir lower examples/collect/main.kir --passes order_dataflow,expand_collect
kir graph examples/collect/main.kir --data wires -o collect.kirgraph
kir text collect.kirgraph
```

The syntax names the yielded value and the result explicitly:

```text
(items)collect(item, index, `body`, value -> results)
```

The input is eagerly snapshotted. Each normally completed body contributes one
value, in input order; the index is optional. `main.kir` maps a branch (`None` for
negative inputs) and then demonstrates nested collections, including an empty
inner collection. It produces:

```text
result = [3, None, 7]
rows = [[], [0, 1], [0, 1, 4]]
```

`collect` is not an implicit filter or a reduction. Body state follows the same
flat/carried rules as `each`; normal completion samples the named value. Its
result is assigned only after the entire collection succeeds, and an empty
input assigns `[]`. An escaping failure leaves the old target unchanged and
preserves earlier body writes and effects. A failure caught inside the body can
still produce that iteration's value on normal completion. Input snapshot errors
are catchable failures attributed to `kir.collect_items`.

Yielded values are retained by reference, not deep-copied. This increment therefore
rejects declared `mutates` calls throughout programs containing `collect`; the body
cannot read or write the collection target, and jumps cannot escape it. Ordinary
`each` semantics are unchanged. General mutable-alias collection is not implied.

The runner checks every lowering pass prefix and both graph views against direct
reference execution. The direct reference keeps one private list and uses append;
its control bookkeeping does not invoke host-call hooks. `expand_collect` is an
explicit correctness baseline: `kir.collect_items` snapshots the input, a private
accumulator feeds `each`, `kir.collect_append` creates a fresh list on each normal
completion, and a final assignment publishes the result. Internal names avoid
shadowing by a user's `append` node. Expanded replay must use the same expanded
reference: its helper calls are ordinary recorded calls, unlike direct control
bookkeeping.

## Cheap allocation-work acceptance check

```sh
python -m pytest tests/test_collect_reference.py -k "copy_work or allocation_counts" -q
```

These tests count work rather than time a slow host node. A test-only interpreter
observer checks that each normal completion adds exactly one reference to the
**same** private list, including final publication. An instrumented baseline helper
checks that each call returns a new list and sums its result lengths, including
the appended reference. For a collection of size `n`, direct capture has `n`
placements; baseline accumulation has `1 + ... + n = n(n+1)/2` placements and `n`
fresh result lists. Tests cover `n = 0, 1, 4, 32` and nested empty/nonempty builders,
summing their independent costs while requiring identical outputs.

This counts logical list-element placement, not exact allocator bytes or Python's
amortized capacity growth. Input snapshotting and the constant number of empty
builder allocations are separate linear/constant overheads; no walltime threshold
or scheduler speedup is inferred. Generated origins (`collect.items`, `collect.init`,
`collect.append`, `collect.result`) attribute baseline bookkeeping without adding
new metadata syntax.
