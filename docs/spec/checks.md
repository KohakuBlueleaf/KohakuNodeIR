# Checks

The checker runs before lowering. Errors stop lowering; warnings do not. Each
rule has a code, and the test corpus holds one wrong program per rule that
must trigger it.

## Errors

| Code | Rule |
|---|---|
| `E001` | Syntax error. |
| `E002` | `@use` after a statement, or a library that does not resolve. |
| `E010` | Unknown node: not in a used library, not a `@def`, not a builtin. |
| `E011` | Ambiguous node: the name is in two unaliased libraries. |
| `E012` | Call shape: too many positional inputs, an unknown keyword, a required input missing, or the wrong number of outputs. |
| `E013` | Reserved name: a name or label contains `__`, or a call uses the `kir.` prefix. |
| `E020` | A name is read where some path reaching it never wrote it; collection yield reads occur at body completion, not entry. |
| `E021` | A `@def` output is not written on every path through the body. |
| `E030` | A label a builtin names does not exist in the scope where it must be found. |
| `E031` | A namespace named by more than one `branch`, `switch`, `parallel` or `each` label. Only `jump` may name a namespace more than once (that is how loops re-enter). |
| `E033` | A dependency cycle inside a `@dataflow:` block. |
| `E032` | `jump` into an `each` or `collect` body from outside it. |
| `E040` | Type mismatch: a value's known type does not fit the input's type. `_` fits everything; `int` fits `float`; `T` fits `T?`. |
| `E041` | A `branch` condition whose known type is not `bool`. |
| `E050` | A `@def` calls itself, directly or through others. |
| `E060` | `@mode dataflow` with control flow in the file. |
| `E061` | A `@dataflow:` block holding anything but assignments and calls. |
| `E070` | A collection target is used as an iteration binding/yield or referenced inside its own body. |
| `E071` | An explicit jump leaves a collection body. |
| `E072` | A program containing `collect` also calls a declared `mutates` node; initial collection alias safety forbids this combination. |

## Warnings

| Code | Rule |
|---|---|
| `W001` | A namespace nothing enters. |
| `W010` | `parallel` arms contradict "no order": two arms write the same name, or one reads a name another writes. |
| `W020` | Inside a `@def` body, a name is written and never read (outputs discarded with `_` are not counted; the top level's final values are the job's results, so it is not checked). |
