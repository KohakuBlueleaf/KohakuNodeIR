# Source programs and execution contracts

KIR defines a job by its sequential control and value semantics. An executor
binds its node calls to implementations and supplies their outcomes. These are
different contracts: a source program does not, by itself, specify clocks,
service reliability, retry attempts, or cancellation delivery.

This document introduces no KIR syntax, signature effect, or reference clock.
See [semantics.md](semantics.md) for source behavior and [signatures.md](signatures.md)
for the existing `mutates` and `ordered` obligations.

## Categories

| Category | Examples | Contract |
|---|---|---|
| Source program | Inputs, calls, branch conditions, namespace control, `@try` handlers | Determines how values and exposed call failures affect the job. |
| Signature effects | `mutates`, `ordered` | Constrain alias handling, ordering, and replay. They are not scheduling hints. |
| Advisory annotations | `@hint lane="vlm"`, batching preferences, editor `@meta` | May be ignored or deleted without changing source results. KIR assigns no meaning to hint keys. |
| Executor binding policy | Observable timeout, retry or cancellation behavior; step/work budgets | Determines which attempts occur and which outcomes or terminal statuses the executor exposes. Must be explicit in the execution contract, not silently treated as advisory. |
| Outcome trace | Returned values, exposed failures, selected dynamic invocations | Evidence for checking the source control/value behavior under those outcomes. Not a guarantee that another physical run produces them. |

A preference is advisory only when honoring or ignoring it preserves behavior.
A setting that can replace a successful value with an error, select a handler,
repeat externally visible effects, or terminate the job is observable policy,
regardless of whether its name contains “hint.”

## Source semantics versus a particular run

For fixed inputs and a supported sequence of node outcomes, the sequential
reference determines the branches, handler selection, retained writes, and
final values. Deleting `@hint` and `@meta` must not change that behavior. In
particular, `@hint timeout_s=...` does not instruct the KIR reference to measure
elapsed time, and `@hint retry=...` does not instruct it to repeat a failed call.

An executor may expose a timeout as a node failure, if its binding contract
specifies that mapping. KIR then applies the ordinary `@try`/`@except` rules to
the exposed failure. Alternatively, an executor may report cancellation or a
resource-limit failure outside KIR's catchable node-error channel. Those
mappings must be documented; this specification does not equate every terminal
executor status with a catchable exception.

Retries can involve more physical attempts than logical KIR calls. A retry
policy must say which outcome becomes visible, how attempts are recorded, and
what happens to external effects. Retrying does not undo an earlier effect,
and `ordered` does not mean “safe to retry.” Existing signature effects remain
unchanged. Cancellation of already-running host work likewise does not imply
that its external effects have been rolled back.

External implementations may depend on random state, clocks, changing services,
or behavior unavailable to KIR. Unknown or undeclared nondeterminism is not
made deterministic by a semantic hash, a scheduler hint, or a replay. Node
authors still owe the declared input/effect contract; the executor must not
assume arbitrary external implementations are interchangeable merely because
their signatures match.

## Fixed-outcome replay

A reference call hook can inject recorded successful values or raise a recorded
error instead of invoking the host implementation. This checks that the source
consumes those outcomes correctly, including skipping calls on untaken paths
and entering the correct handler. It does **not** establish:

- That the reference reproduced elapsed-time deadlines or physical scheduling.
- That an external service will return the same value on another run.
- That retries or cancelled attempts had no external effects.
- That a flat trace can be reused across transformations without matching
  dynamic invocations and accounting for generated administrative calls.

Record binding identity and relevant policy alongside the trace. For repeated
calls, an occurrence/call-site identity is needed in addition to the node name.
An executor's detailed replay format and attempt-level evidence belong to its
own execution contract.

## Resource limits and hashes

Step and work budgets are observable execution choices, not free hints. The
Python reference's optional `step_budget` is a node-call bound, not an elapsed
time deadline. Pass expansion can introduce internal administrative calls, so
the same numeric budget applied independently to source and lowered programs
may be exhausted at different points. Semantic preservation does not promise
identical termination under every independently applied resource limit; the
comparison assumes supported matched outcomes and limits that are not exhausted,
or an executor-defined accounting scheme that preserves that correspondence.

The semantic program hash excludes hints and metadata. It identifies source
semantics, not an entire physical execution or a sufficient cache key for every
external implementation. The full hash also includes hints, but still does not
identify out-of-band binding policy, implementation versions, input values, or
outcome traces. Executors must include the additional identity required by
their cache/replay contract; this document does not change KIR hashing.

## Identity layers

Keep the following identities distinct rather than treating one digest as a
certificate of reproducibility:

1. **Program representation:** KIR's low-level semantic/full hashes describe the
   supplied canonical representation, not the implementations behind its calls.
2. **Resolved contracts and dependencies:** module and signature contract hashes
   describe imported source, ports, defaults, record schemas, and effect flags.
   Dependency-aware `Compiled` hashes include the manifest when present. Legacy
   programs without source modules or records retain their historical hashing;
   their program hash must not be assumed to cover every resolved host signature.
3. **Executor binding:** a separate execution manifest can identify the selected
   implementations/adapters, declared revisions, and observable policy under its
   own versioned contract. An execution digest covers the information actually
   recorded, not information the executor does not possess.
4. **Inputs and outcomes:** input identity and the observed dynamic outcome trace
   describe a particular invocation/run. They are not implied by program or binding
   identity, and matching identities do not eliminate external nondeterminism.

A missing implementation revision is **unknown**, not a known compatible match.
Serializing or hashing two unknown markers does not turn them into evidence of
implementation equality. Do not fabricate a strong fingerprint from a function's
name, object address, or a partial inspection of its code: these do not establish
identity of captured state, dependencies, or external services. An executor may
require explicit revisions, reject reuse, or permit an explicitly documented
weaker compatibility mode. Its restore/cache policy must state that choice.

This layering adds no new KIR hash field or hashing rule. Runtime manifests and
their validation APIs belong to the executor; KIR's source-level semantic and
advisory-hint contracts remain unchanged.

## Togeari timeout migration boundary

**Compatibility warning:** legacy Togeari interpreted a statement's
`@hint timeout_s` as an observable item timeout. This is historical executor
compatibility behavior, not KIR advisory-hint semantics. Deleting that hint in
legacy inference mode can change the physical run; users must not mistake that
mode for the advisory-deletion guarantee.

The current public binding API makes this distinction explicit:

- `ExecutionPolicy(timeout_s: float | None = None)` holds the item timeout policy.
- `Use(..., policy=None)` selects legacy inference for compatibility; legacy
  `timeout_s` use must produce a migration warning.
- `Use(..., policy=ExecutionPolicy(timeout_s=seconds))` selects an explicit item
  timeout independently of KIR hints.
- `Use(..., policy=ExecutionPolicy())` explicitly disables the item timeout; it
  does **not** request legacy inference and must not re-enable it from hints.

Older Togeari releases may not expose this API and may still infer observable
timeouts from hints. Consult the execution-policy documentation for your installed
runtime version before migrating; the compatibility warning above still applies.
A lane's timeout remains a separate **per-attempt** execution policy; disabling
the item timeout does not disable lane, engine, or other independent limits.
Their clock origins, precedence, retry interactions, and error mapping belong
to the runtime contract. No program-level deadline directive is introduced.
