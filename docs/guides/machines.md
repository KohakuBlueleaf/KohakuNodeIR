# Running KIR on a machine

A machine receives KIR text plus engines that implement its nodes. It never
needs to know how the text was made (editor, hand-written, generated).

## What to run

Compile once per program:

```python
compiled = compile_source(text, libraries)  # check + every optimization pass
program = compiled.lowered  # what to execute
compiled.semantic_hash  # program component of cache/replay identity
```

A job is one run of the program (or of one `@def`, chosen by the machine),
with its inputs bound to that `@def`'s parameters. The program hash is not a
complete cache key: an executor must also account for resolved contracts,
implementation/binding identity, relevant policy, and inputs. Unknown
implementation revisions remain unknown, not evidence of a compatible match
([identity layers](../spec/execution-contract.md#identity-layers)).

A machine may also pick its own passes (`passes=[...]`, docs/spec/passes.md),
for example to keep `each` as a single node it schedules itself.

## What the fully optimized program guarantees

- Statements outside `@dataflow:` blocks are control: `branch`, `switch`,
  `jump`, `parallel`, `@try`, namespaces. They decide which block runs next.
- Each `@dataflow:` block is a straight run, already in a valid order. A
  statement depends on the last earlier statement in the block that writes a
  name it reads; the machine may start it as soon as those values exist.
  Names written more than once (`x__0`, home versions) also order by earlier
  readers and writers unless the machine renames values as it runs.
- Node flags from the signatures: `ordered` nodes keep program order within a
  job; `mutates` nodes wait for earlier readers of the value they change.
- `@hint` keys are advisory scheduling preferences (for example lane or
  batching preferences). They never change results and are not in the semantic
  hash. Observable retries, timeouts, cancellation, and work limits belong to
  executor binding policy, not advisory hints; see the
  [execution contract](../spec/execution-contract.md).
- A job's state is its position plus its value slots, so it stays plain data.

## Correctness check

The reference interpreter defines the result. To check a machine, run sample
jobs on both and compare. Engines that sample (VLMs) must be replayed: give
the reference interpreter a call hook that returns the machine's recorded
outcome for each logical invocation, not a shared result for each distinct input.
For a small reference run, an ordered occurrence trace can be consumed as follows:

```python
from collections import deque
from copy import deepcopy

# Each entry belongs to one logical invocation, in reference traversal order.
# Repeated equal-input calls remain separate entries. `error` is None or the
# reconstructed exception to expose, not an unprocessed retry-attempt record.
pending = deque(recorded_occurrences)


def replay(name, inputs, call):
    expected_name, expected_inputs, value, error = pending.popleft()
    assert name == expected_name and inputs == expected_inputs
    if error is not None:
        raise error
    return deepcopy(value)


interp = Interpreter(compiled.lowered, compiled.env, hook=replay)
interp.run()
assert not pending
assert interp.source_values() == machine_values
```

This illustrative queue is not a parallel completion-order log. Associate
records with dynamic invocations, match them to reference traversal, and account
for generated administrative calls before constructing it. Input comparison or
digests must follow the value codec's contract. A dictionary keyed only by
`(node, input_digest)` is insufficient when repeated requests have distinct
outcomes. Replay checks control/value consumption under recorded outcomes; it
does not certify determinism or authorize cross-invocation caching
([invocations and reuse](../spec/execution-contract.md#logical-invocations-attempts-and-reuse-eligibility)).

A machine whose jobs run one `@def` checks against the program as written,
where the `@def` still exists:

```python
pending = deque(recorded_definition_occurrences)  # a fresh, matched trace
interp = Interpreter(compiled.program, compiled.env, hook=replay)
assert interp.call("gbc", job_inputs) == machine_outputs  # outputs by name
assert not pending
```
