# Running KIR on a machine

A machine receives KIR text plus engines that implement its nodes. It never
needs to know how the text was made (editor, hand-written, generated).

## What to run

Compile once per program:

```python
compiled = compile_source(text, libraries)   # check + every optimization pass
program = compiled.lowered                    # what to execute
compiled.semantic_hash                        # cache / reproducibility key
```

A job is one run of the program (or of one `@def`, chosen by the machine),
with its inputs bound to that `@def`'s parameters.

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
- `@hint` keys are scheduling hints (lane, retry, max wait, priority). They
  never change results and are not in the semantic hash.
- A job's state is its position plus its value slots, so it stays plain data.

## Correctness check

The reference interpreter defines the result. To check a machine, run sample
jobs on both and compare. Engines that sample (VLMs) must be replayed: give
the reference interpreter a call hook that returns the machine's recorded
result for each request.

```python
def replay(name, inputs, call):
    return recorded[(name, request_key(inputs))]

interp = Interpreter(compiled.lowered, compiled.env, hook=replay)
interp.run()
assert interp.source_values() == machine_values
```

A machine whose jobs run one `@def` checks against the program as written,
where the `@def` still exists:

```python
interp = Interpreter(compiled.program, compiled.env, hook=replay)
assert interp.call("gbc", job_inputs) == machine_outputs   # outputs by name
```
