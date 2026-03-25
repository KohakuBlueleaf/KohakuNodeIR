#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRATE_DIR="$SCRIPT_DIR/../src/kohakunode-rs"
OUT_DIR="$SCRIPT_DIR/../kir-editor/frontend/src/wasm"

cd "$CRATE_DIR"

# Build with cargo (avoids wasm-pack's --artifact-dir which requires nightly)
cargo build --target wasm32-unknown-unknown --no-default-features --features wasm --release

# Generate JS glue with wasm-bindgen
mkdir -p "$OUT_DIR"
wasm-bindgen --target web --out-dir "$OUT_DIR" \
  target/wasm32-unknown-unknown/release/kohakunode_rs.wasm

echo "[build-wasm] Output written to $OUT_DIR"
