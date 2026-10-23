# Committed semantic events

`emit` is an ordinary ordered node in `kir.std`, not new grammar or an AST
control construct:

```kir
("progress", {"completed": 1})emit()
```

Its signature is `(topic: str, payload: _)emit()` with zero outputs,
`ordered: true`, and no mutated inputs. Graphs show an ordinary `call` node.
The standard node adds an ordered event sidecar; it does not change a program
variable or turn engine responses into partial-value streams.

## Standard identity and shadowing

Semantic emission is recognized by the maintained standard library, signature,
and implementation identities together, not the spelling `emit` alone.
An authentic alias works:

```kir
@use "kir.std" as std
("progress", 1)std.emit()
```

A user library or `@def` named `emit`, a cloned signature, or a reference
implementation override is an ordinary call. Mutating the global standard
library registry is unsupported. Calling the standard Python implementation
directly only validates its inputs; it does not publish an event.

The standard signature requires ordering and forbids cache substitution. Each
successful dynamic invocation contributes one event, including repeated equal
payloads. A failure before emission contributes none. Later failures do not
remove earlier events: `@try` is not a transaction over the event prefix.

## Portable payload snapshots

Topics must be exact Python strings. Payloads accept exact portable values:
null, bool, arbitrary-size int, finite float, string, lists, string-keyed
dictionaries, and validated `RecordValue` instances. Containers are snapshotted;
subsequent mutation of application containers cannot change an event. Cycles,
nonfinite floats, tuples, opaque objects, and subclasses of portable container
or scalar types are rejected. No properties, attribute-based conversion, or
user-defined serialization methods are invoked.

`kohakunode.records.encode_portable(value)` returns detached encoded data;
`decode_portable(data, schemas=None)` reconstructs application values. The
existing `encode_record`/`decode_record` functions still require a record at
the root. All containers use explicit tags:

```json
[
  {"$kir": "list", "items": [1, 2]},
  {"$kir": "dict", "items": {"completed": 1}},
  {"$kir": "record", "schema": "geometry.Point", "fields": {"x": 1}}
]
```

Scalar values remain scalars. Thus an application dictionary containing a
`$kir` key cannot masquerade as a record: it is itself wrapped with the `dict`
tag. Decoding record tags requires a registry keyed by canonical schema ID;
comparing encoded events for replay does not. A transport may impose its own
size/encoding limits, but these codecs do not change process-wide integer
conversion settings.

## Reference API

```python
from kohakunode import Event, Interpreter, build_env, parse

program = parse('("progress", {"completed": 1})emit()\n')
received = []
interpreter = Interpreter(program, build_env(program), events=received.append)
values = interpreter.run()
assert values == {}
assert received == interpreter.events == [Event.capture("progress", {"completed": 1})]
wire_event = received[0].to_dict()  # detached {"topic": ..., "payload": ...}
application_payload = received[0].decode()
```

`Event.capture(topic, payload)` snapshots application values.
`Event(topic, encoded_payload)` constructs an event from the explicit encoded
form. Both validate and create immutable storage without delivering anything.
`event.payload` is **immutable encoded storage**, not an ordinary application
dictionary; use `to_dict()` for a detached transport mapping or
`decode(schemas=None)` for fresh application values. Event equality preserves
scalar type distinctions (`True`, `1`, and `1.0` are different) and ignores
dictionary insertion order.

`Interpreter(..., *, events=callback)` accepts an optional callback receiving
one immutable `Event`. Independently of the callback, `interpreter.events`
retains the committed sequence in reference execution order. It resets at each
public `run()` or `call()` invocation, not on nested `@def` calls. The convenience
`run(..., events=callback)` function also accepts the keyword-only callback.
The list is a reference/testing collector, not a bounded durable runtime outbox.

## Call hooks, validation, and failures

The event sidecar is independent of the ordinary call hook used for recording
or replay:

1. Capture the immutable topic/payload snapshot before invoking the hook. If
   validation fails, retain the exception without raising it yet.
2. Invoke the hook exactly once for that logical call. Its execution thunk
   raises a retained validation error or invokes the standard validation-only
   implementation. Without a hook, execute the thunk normally.
3. A hook failure produces no event. If a hook returns success despite failed
   payload preparation, reject that impossible success rather than publishing.
4. After successful call completion, append exactly one prepared event to the
   sidecar, then notify the optional callback. Skipping the thunk during replay
   does not skip the event; invoking the thunk twice does not publish twice.

Validation errors remain ordinary catchable node failures and invalid emits
remain visible to recording hooks. A callback error is different: the event
has already committed. The interpreter raises
`EventDeliveryError(KirRuntimeError)` with the delivery exception as its cause.
This error is not a `NodeFailure`, is not caught by KIR `@except`, and does not
remove the committed prefix. Delivery errors are not silently suppressed.

## Executor boundary and replay

A parallel executor must expose the same logical event sequence under matched
outcomes. Preparing an event while issuing work is not publication; speculative
or squashed younger work must not leak events. Earlier committed events survive
later job failure or cancellation. Existing `ordered` effects must not overtake
an earlier uncommitted emission merely because its computation is finished.

Reliable delivery, bounded count/bytes, durable append, consumer acknowledgments,
retrying delivery with the same event ID, and restore-frontier compatibility
belong to the executor's event-output contract. A lossy diagnostic event bus is
not a semantic transport. Do not infer exactly-once consumer effects from an
event ID or an acknowledgment protocol.

Conformance replay regenerates the reference event sidecar from recorded node
outcomes and compares it with the committed sequence, separately from the call
record format. It does not contact real consumers or count delivery retries as
additional semantic events. Missing event evidence for an emitting program is
unverified, not a verified empty event sequence. See
[execution-contract.md](execution-contract.md) for invocation and outcome identity.
