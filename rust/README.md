# kohakunode Rust core

The Rust core of KIR v2. It ships inside the `kohakunode` wheel as the
extension module `kohakunode._rs`, and builds to WebAssembly for the browser
editor. The Python package `src/kohakunode` is the reference: canonical text,
checker diagnostics, the optimization passes, both hashes and the graph view
are byte-identical to it on every case of `tests/corpus/golden`.

Modules mirror the Python layout: `syntax/` (pest grammar `kir.pest` over the
text marked by `indenter.rs`, AST, writer), `sig/`, `flow/`, `check/`, `lower/`
(the passes), `graph/`, plus `util/` (Python-compatible JSON, `repr` and path
text) and `bindings/` (PyO3, wasm-bindgen).

## Build and test

```sh
# from the repo root: the kohakunode package with kohakunode._rs (one wheel per Python 3.10-3.14)
pip install -e .                  # or: maturin develop --release
python rust/tests/parity/parity.py   # every output against the Python reference

# from rust/
cargo test --release              # unit tests + every golden case (tests/golden.rs)
cargo clippy --all-targets -- -D warnings
cargo clippy --features python -- -D warnings
```

Under conda or micromamba, `unset CONDA_PREFIX` before `maturin develop`
(maturin refuses when both it and `VIRTUAL_ENV` are set).

WebAssembly:

```sh
cargo build --release --target wasm32-unknown-unknown --features wasm
wasm-bindgen --target web --out-dir pkg target/wasm32-unknown-unknown/release/kohakunode_rs.wasm
# the golden corpus through the wasm build, in Node:
wasm-bindgen --target nodejs --out-dir target/wasm-node target/wasm32-unknown-unknown/release/kohakunode_rs.wasm
node tests/wasm/golden.cjs
```

`wasm-bindgen` (the CLI) must match the `wasm-bindgen` crate version in
`Cargo.lock`. The default feature `unicode-names` holds the Unicode name table
for `\N{...}` string escapes: 1.9 MB of wasm with it, 1.0 MB without
(`--no-default-features --features wasm`, where `\N{...}` is a syntax error).

## `kohakunode._rs`

`sigs` is a list of `.kirsig.json` texts given as unaliased libraries. `base`
(the program's directory, for `@use "x.kirsig.json"`) and `sig_path`
(directories searched for `<library>.kirsig.json`, then `KIR_SIG_PATH`) resolve
`@use` as `build_env` does; both take `str` or path objects.

| Function | Returns |
|---|---|
| `format(source)` | canonical text |
| `parse_to_json(source)` | the AST as JSON: `{uses, mode, body}`; statements have `kind`, `line`, `meta`, `hint` and their fields; expressions `{"name"}` / `{"literal"}`; types as text |
| `check(source, sigs=[], *, base=None, sig_path=[])` | JSON list of `{code, message, line, severity}`; an unresolvable `@use` is `E002` |
| `lower(source, sigs=[], passes=None, *, base=None, sig_path=[])` | text after the passes (default all: `order_dataflow, inline, expand_each, version, group, strip_meta`) |
| `hashes(source, sigs=[], passes=None, *, base=None, sig_path=[])` | `hashes.json` text: `{"semantic", "full"}` |
| `to_graph(source, sigs=[], data="wires", *, base=None, sig_path=[])` | `.kirgraph` text (`json.dumps(indent=2, ensure_ascii=False) + "\n"`); `data="variables"` draws every read as a `get` node and every write as a `set` node |
| `from_graph(graph, with_meta=True)` | canonical text of a `.kirgraph` |
| `std_signatures()` | the `kir.std` signature file |

Errors: `KirSyntaxError`, `KirCheckError`, `KirSignatureError`, `KirGraphError`
(subclasses of `kohakunode._rs.KirError`), and `ValueError` for values without
a KIR or JSON form and for an unknown data style. Signature failures come back as the reference reports them:
`E002` from `check`, `KirCheckError` holding `E002` from `lower` / `hashes`
(as `compile_program`), `KirSignatureError` from `to_graph` (as `build_env`).

The wasm exports are the same functions in camelCase (`parseToJson`, `toGraph`,
`fromGraph`, `stdSignatures`) taking signature texts only (no filesystem);
`toGraph(source, sigs, data)` takes `undefined` for `"wires"`. Errors are JS
`Error`s whose message starts with the error class.
