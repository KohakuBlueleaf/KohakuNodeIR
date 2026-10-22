# Source modules and origins

Source modules reuse KIR subgraph implementations without hiding their internal
calls or control flow. They are distinct from host signature libraries:

- `@use "host" as h` imports host-node signatures, as before.
- `@import "transforms.kir" as t` imports exported KIR definitions.
- `@export transform` publishes one top-level definition from this module.

These directives form the declaration preamble, before statements. An import
requires an alias. Export several definitions with several `@export` directives.

```text
# transforms.kir
@export transform
@def (xs: list, enabled: bool = True)transform(result: list):
    result = []
    (xs)each(x, `body`)
    body:
        (enabled)branch(`yes`, `no`)
        yes:
            (result, x)append(result)
        no:
            skipped = x
```

```text
# main.kir
@import "transforms.kir" as t
@def (xs: list)main(result: list):
    (xs)t.transform(result)
```

## Resolution and visibility

An imported file is a declaration-only library: definitions, type hints, and
preamble declarations. It cannot contain executable top-level statements or a
file-wide dataflow mode. Importing it executes no node implementations. Entry
programs retain their existing top-level execution semantics.

Only explicitly exported top-level definitions are callable through an import
alias. Private definitions remain available inside their defining module. Imports
are not implicitly re-exported. A wrapper definition can explicitly expose an
imported implementation. An export of a missing name or a duplicate export is an
error. Duplicate definitions and conflicting import aliases are errors. Import
aliases cannot also name local definitions or host signature aliases.

Imports resolve relative to the importing module's resource directory. Resource
IDs use relative POSIX paths, independent of the host OS. `.` and `..` components
are normalized; a resource must remain inside the package root. Absolute paths,
backslashes, and drive/URL prefixes are rejected. Filesystem resolution also
rejects symlinks escaping that root. A moved checkout retains the same logical
resource IDs. Moving or renaming a module *inside* the package changes its ID.

For `compile_file(path)`, the entry's directory is the package root and its file
name is the entry resource ID. `compile_source` and `compile_program` accept
keyword-only `modules` and `source_name` arguments. `modules` maps normalized
package-relative IDs to source text. When supplied, this map is authoritative:
missing entries are errors, not a reason to fall back to the filesystem. Without
a map, source imports require a `base_dir` package root. `source_name` defaults
to `<text>` and otherwise is a package-relative resource ID. No remote registry
or implicit network resolution is involved.

```python
from kohakunode import compile_source

compiled = compile_source(
    '@import "identity.kir" as lib\n(7)lib.identity(result)\n',
    modules={
        "identity.kir": "@export identity\n@def (x: int)identity(y: int):\n    y = x\n"
    },
    source_name="main.kir",
)
```

Import cycles are errors, with the import chain reported. Direct and indirect
subgraph recursion remain prohibited after linking. Linking is not runtime
subgraph dispatch and does not add recursion.

## Linking and types

Linking runs before the existing checker and transformation passes. Imported
bodies become ordinary definitions under deterministic generated names; calls
and local host signature aliases are rewritten accordingly. Private names from
different modules cannot collide. Generated definition names use a reserved
`_kir_` prefix when modules are linked. Author-written names (definitions,
variables, labels, types, calls, type hints, and host/import aliases) in a modular
program must not use that prefix. This prevents capture of generated names during
linking and inlining. Already-linked programs without import/export declarations
can still be read and executed. Imported type hint names are qualified separately
from definitions, preserving dotted names without collapsing them into underscore
names.

The checked `Compiled.program` is the linked program. `Compiled.source_program`
is the authored representation with its imports and exports. `Compiled.lowered`
is the selected transformed representation. `link_program` exposes the linking
step separately, returning a `Linked` program, its resolved signature libraries,
and dependency manifest. Signature discovery does not import host implementation
code; execution still requires implementations as usual.

Builtin value types keep their existing identity. Host signature types keep the
identity declared by their signature contract. Other nominal types in a modular
program are qualified by their defining module. A nominal type appearing in an
exported subgraph's signature can be named as `alias.Type` by its importer. This
does not introduce structural records or automatic equivalence between unrelated
nominal types. If an exported wrapper uses an imported type such as `inner.Token`,
its importer refers to that type as `outer.inner.Token`; resolution follows the
exported signature back to the original defining module. It does not create a
new type or implicitly re-export every private type. Schemas and field operations
are a separate language extension.

Graph conversion preserves imports and exports as declarations, not executable
nodes. Linked graph conversion exposes the linked definitions and ordinary calls.
Text written from the linked representation is valid KIR without source imports.

Node names in execution hooks, replay records, and `@except` error values identify
the **linked executable call spelling**. Imported host calls can therefore have a
qualified generated spelling different from the same call in a handwritten local
body. This is a declared namespace distinction, not a source-origin lookup:
source origins provide the original module, definition, and call sites separately.
Existing non-modular node names and handler values are unchanged. Code comparing
an error's `node` string must use its executable namespace; it must not assume
that generated names are stable across module renames or linker-format changes.

## Dependency identity

`Compiled.dependencies` is empty for legacy programs without import/export
declarations. Modular compilation produces a version-1 manifest containing:

- Modules sorted by resource ID, each with its canonical semantic source hash,
  resolved import-alias map, and sorted exports.
- Resolved signature contracts sorted by library name. Contract hashes include
  ports, types, defaults, and effect flags; documentation is excluded.
- A manifest hash over compact sorted-key UTF-8 JSON of the preceding fields.

Module source hashes exclude editor metadata and scheduling hints. Transitive
module content, including presently unused declarations, contributes to the
manifest. Absolute checkout locations and implementations do not. This is a
conservative dependency identity, not a claim to fingerprint arbitrary Python
functions or remote services. Signature-file paths are normalized to resolved
library names before hashing modular source, so an absolute signature search
location does not leak into dependency identity. Modular signature defaults must
be portable JSON data: exact builtin null/bool/int/string values, finite floats,
lists, and string-keyed dictionaries recursively. Cycles, tuples, custom objects
or container subclasses, non-string keys, and nonfinite floats are rejected rather
than silently sharing identity with a different default. These restrictions apply
to modular contract identity; legacy non-modular compilation is unchanged.
Nonportable defaults produce a signature diagnostic rather than a raw serialization
failure. `kohakunode.modules.contract_hash(library)` exposes the
same contract identity for consumers checking restore/replay compatibility.

For modular compilation, `Compiled.semantic_hash` and `Compiled.full_hash` mix
the corresponding linked/lowered text hash with the dependency manifest hash,
using SHA-256 of `text_hash + "\x1f" + manifest_hash`. Legacy hashes remain
unchanged. Low-level `semantic_hash(program)` and `full_hash(program)` continue
to identify the supplied representation; they do not resolve dependencies.

## Structured source origins

Origins are separate from editor metadata, hints, and semantic identity. A
statement may carry an `Origin` with:

- `module`: logical source resource ID;
- `node_id`: supplied graph/editor node ID, or a structural fallback;
- `line`: source line when known;
- `definition`: original enclosing definition, when present;
- `calls`: flat outermost-first subgraph call-site ancestry; each call-site entry
  is a shallow location with empty `calls`, avoiding duplicated recursive history;
- `generated`: attribution for a generated operation, when present.

Compilation stamps missing origins before linking or lowering. Supplied node IDs
are retained. Text fallback IDs identify a structural statement position: they
survive formatting that preserves statement structure, but not arbitrary edits
that insert, delete, or move statements. Source lines are locations, not durable
identities. Origins survive `strip_meta` and do not affect AST semantic equality
or program hashes.

Inlining retains definition origins and adds call-site ancestry, so two copies
of the same subgraph can be distinguished without parsing generated variable
names. Generated argument/output assignments and iteration/versioning operations
remain attributable to the source operation that produced them.

Graph conversion carries origins separately from editor metadata. Canonical text
alone does not serialize an inlining ancestry tree: persisting transformed code
with its full attribution requires the graph/origin sidecar representation.
Dynamic job, iteration, invocation, and attempt identities are not source origins.

The reference interpreter attaches the originating statement to
`NodeFailure.origin`, adding call-site ancestry when an unlowered subgraph call
propagates a failure. This diagnostic attribute does not change the error value
passed to a KIR exception handler or the underlying host exception message.
