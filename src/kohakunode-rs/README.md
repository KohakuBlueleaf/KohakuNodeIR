# kohakunode-rs

Rust implementation of the KIR language core. Mirrors the Python `kohakunode`
package and provides the same parser, compiler, KirGraph, layout, and serializer
functionality with better performance.

## Module structure

| Module | Description |
|---|---|
| `parser/` | PEG parser (pest) for `.kir` source -> AST |
| `ast/` | AST node types matching the Python definitions |
| `compiler/` | `compile_dataflow` and `strip_meta` AST transforms |
| `kirgraph/` | KirGraph schema, compiler (L1 -> L2), and decompiler (L2 -> L1) |
| `layout/` | Auto-layout, scoring, and optimization for node graphs |
| `serializer/` | AST -> `.kir` text serializer |
| `analyzer/` | Static validation |
| `pyo3_module.rs` | PyO3 bindings (Python extension module) |
| `wasm_module.rs` | wasm-bindgen exports (browser WASM module) |

## Build targets

### Python extension (PyO3)

Used by the Python `kohakunode` package to accelerate parsing and layout.

```bash
cd src/kohakunode-rs
pip install maturin
maturin develop --release
```

This produces a `kohakunode_rs` Python module. The Python package detects it
automatically via `_rust.py`.

### WASM (browser)

Used by the kir-editor frontend for in-browser parsing and layout.

```bash
# From the repo root:
bash scripts/build-wasm.sh
```

This runs `cargo build --target wasm32-unknown-unknown` with the `wasm` feature,
then `wasm-bindgen` to generate JS glue. Output goes to
`kir-editor/frontend/src/wasm/`.

### Rust library

```bash
cargo build --release
```

## Features

| Feature | Default | Description |
|---|---|---|
| `python` / `pyo3` | yes | PyO3 extension module |
| `wasm` | no | wasm-bindgen + console_error_panic_hook |

## Dependencies

- [pest](https://pest.rs/) for PEG parsing
- [serde](https://serde.rs/) / serde_json for JSON serialization
- [thiserror](https://docs.rs/thiserror) for error types
- [PyO3](https://pyo3.rs/) (optional) for Python bindings
- [wasm-bindgen](https://rustwasm.github.io/wasm-bindgen/) (optional) for WASM

## WASM API

All WASM exports take and return JSON strings:

- `parse_kir(source)` -- parse `.kir` text to AST JSON
- `compile_dataflow(program_json)` -- reorder dataflow blocks
- `strip_meta(program_json)` -- remove `@meta` annotations
- `compile_kirgraph(kirgraph_json)` -- L1 graph -> L2 AST
- `decompile(program_json)` -- L2 AST -> L1 graph
- `kir_to_graph(source)` -- `.kir` text -> KirGraph JSON
- `auto_layout(graph_json)` -- run auto-layout on a graph
- `optimize_layout(graph_json, max_iterations)` -- iterative layout optimizer
- `score_layout(graph_json)` -- score a graph layout
- `write_kir(program_json)` -- AST JSON -> `.kir` text

## Documentation

See [docs/](../../docs/) for the full language specification and API reference.
