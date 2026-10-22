# kohakunode Rust core

The Rust core of KIR v2. It ships inside the `kohakunode` wheel as the
extension module `kohakunode._rs`, and builds to WebAssembly for the browser
editor. The Python package `src/kohakunode` is the reference: canonical text,
checker diagnostics, source-module linking, the optimization passes, both hashes and the graph view
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
| `link_modules(source, modules, source_name="<text>", sigs=[])` | JSON `{text, program, dependencies}` after linking; `modules` is a JSON object mapping portable module IDs to source strings |
| `compile_modules(source, modules=None, source_name="<text>", sigs=[], passes=None, *, base=None, sig_path=[])` | JSON `{text, lowered_text, program, lowered, dependencies, semantic, full, diagnostics}` after linking/checking/passes; AST fields retain structured origins |

Errors: `KirSyntaxError`, `KirCheckError`, `KirSignatureError`, `KirGraphError`
(subclasses of `kohakunode._rs.KirError`), and `ValueError` for values without
a KIR or JSON form and for an unknown data style. Signature failures come back as the reference reports them:
`E002` from `check`, `KirCheckError` holding `E002` from `lower` / `hashes`
(as `compile_program`), `KirSignatureError` from `to_graph` (as `build_env`).

The wasm exports are the same functions in camelCase (`parseToJson`, `toGraph`,
`fromGraph`, `stdSignatures`) taking signature texts only (no filesystem);
`toGraph(source, sigs, data)` takes `undefined` for `"wires"`. Errors are JS
`Error`s whose message starts with the error class.

The additional `linkModules(source, modules, source_name, sigs)` and
`compileModules(source, modules, source_name, sigs, passes)` WASM exports accept
an authoritative JSON source-module map; missing source resources never fall
back to filesystem reads. Supply host signature texts through `sigs` (or use
built-in `kir.std`) for filesystem-free operation. Origins are AST/graph sidecar
data, not text directives, and survive metadata stripping. Canonical text alone
cannot preserve an inlining ancestry chain; retain the AST/graph sidecar when
persisting transformed code.

The existing Python-extension `check`, `lower`, and `hashes` entry points also
link filesystem imports when their `base` argument supplies a package root.
They use `<text>` as the entry resource ID. Use the explicit module-map APIs
when a named entry, portable in-memory resources, or origin-bearing output is
needed. Python `compile_modules(..., modules=None, base=...)` selects filesystem
resolution, while `modules="{}"` is an authoritative empty map. Its
`KirCheckError.diagnostics` attribute is JSON text containing every diagnostic
(code, message, line, severity), including warnings emitted alongside errors. `format`, `parse_to_json`, and `to_graph` retain the authored module
declarations rather than implicitly linking them.

Rust callers can use `modules::link_program` with an optional `ModuleMap`, or
`compiler::compile_program_with_modules`. Existing `compile_program` remains
source-compatible and resolves modular imports under its `base_dir` when no map
is provided. `Compiled.source_program` retains authored imports/exports;
`Compiled.program` is linked. `Compiled.dependencies` contains the deterministic
version-1 manifest for modular sources, and `{}` for legacy sources. The exact
language/link/hash contract is in [`docs/spec/modules.md`](../docs/spec/modules.md).

Additional focused checks (from the repository root):

```sh
cargo test --manifest-path rust/Cargo.toml --test linking --test modules_origins
python rust/tests/parity/modules.py
node rust/tests/wasm/modules.cjs
```

On Windows, `modules.py --extension /absolute/path/to/kohakunode_rs.dll` can load
a freshly built native library without installing a wheel. Do not rebuild that
same DLL while a differential test process has it loaded; Windows locks it.
