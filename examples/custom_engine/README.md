# Custom Execution Engines

KIR separates **what** a program does (the AST / dataflow graph) from **how**
functions are called (the `ExecutionBackend`). By subclassing `ExecutionBackend`
you can intercept every function invocation and add caching, profiling,
distributed dispatch, or any other cross-cutting concern -- without changing the
KIR program itself.

## When to use a custom engine

- **Caching / incremental execution** -- skip nodes whose inputs have not
  changed since the last run (see `comfyui_style.py`).
- **Profiling** -- measure wall-clock time per node to find bottlenecks
  (see `pipeline_profiler.py`).
- **Distributed execution** -- serialize invocations and send them to remote
  workers (see `distributed_stub.py`).
- **Logging / auditing** -- record every call for debugging or compliance
  (see `../custom_backend/logging_backend.py`).

## Examples in this directory

| File | Description |
|---|---|
| `comfyui_style.py` | Output caching, node state, and IS_CHANGED (ComfyUI-inspired) |
| `distributed_stub.py` | Conceptual distributed dispatch with JSON serialization |
| `pipeline_profiler.py` | Per-node execution profiling with summary table |
