# scripts

Build and utility scripts for KohakuNodeIR.

## build-wasm.sh

Builds the Rust crate (`src/kohakunode-rs/`) to WebAssembly for use in the
kir-editor frontend.

```bash
bash scripts/build-wasm.sh
```

### What it does

1. Runs `cargo build --target wasm32-unknown-unknown` with the `wasm` feature
   (no default features, so PyO3 is excluded)
2. Runs `wasm-bindgen --target web` to generate JS glue code
3. Outputs the `.wasm` file and JS bindings to
   `kir-editor/frontend/src/wasm/`

### Prerequisites

- Rust toolchain with the `wasm32-unknown-unknown` target:
  ```bash
  rustup target add wasm32-unknown-unknown
  ```
- `wasm-bindgen-cli`:
  ```bash
  cargo install wasm-bindgen-cli
  ```
