# kohakunode

Python reference implementation of the KIR language. Provides a parser, compiler
pipeline, execution engine, and serializer for `.kir` programs.

## Modules

| Module | Description |
|---|---|
| `ast/` | AST node definitions (`Program`, `FuncCall`, `Assignment`, etc.) |
| `parser/` | PEG/LALR parser that turns `.kir` source into an AST |
| `grammar/` | Lark grammar file (`kir.lark`) driving the parser |
| `compiler/` | AST-to-AST transforms: `DataflowCompiler` (ordering) and `StripMetaPass` |
| `engine/` | Runtime: `Registry` (function table), `Executor`, `Interpreter`, `VariableStore` |
| `analyzer/` | Static validation pass (`validate`, `validate_or_raise`) |
| `kirgraph/` | KirGraph (L1 IR): `KirGraphCompiler` (L1 -> L2) and `KirGraphDecompiler` (L2 -> L1) |
| `layout/` | Graph layout algorithms for visual node placement |
| `serializer/` | `Writer` (AST -> `.kir` text) and `read`/`read_string` (file -> AST) |
| `errors.py` | Error hierarchy: `KirSyntaxError`, `KirRuntimeError`, etc. |
| `_rust.py` | Optional Rust backend detection (`HAS_RUST` flag) |

## Quick usage

```python
from kohakunode import parse, run, validate

# Parse
program = parse("x = 1\n(x, x) add (result)\n")

# Validate
result = validate(program)
assert result.ok

# Execute
from kohakunode import Registry, Executor
registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])
executor = Executor(registry=registry)
variables = executor.execute_source(source)
```

## Compilation pipeline

```
.kir source -> parse() -> AST (L2)
                            |-> DataflowCompiler  (reorder dataflow blocks)
                            |-> StripMetaPass     (L2 -> L3, remove @meta)
                            |-> Writer            (AST -> .kir text)

KirGraph (L1) -> KirGraphCompiler -> AST (L2) -> ... same pipeline
AST (L2)      -> KirGraphDecompiler -> KirGraph (L1)
```

## Installation

This package is installed as part of the top-level project:

```bash
pip install -e .
```

If the Rust extension (`kohakunode-rs`) is available, the Python package
automatically delegates parsing and layout to the faster Rust implementation.

## Documentation

See [docs/](../../docs/) for the full language specification and API reference.
