# Typed records and explicit field operations

Records describe structured values without hiding field operations inside opaque
host functions. Schemas live in signature libraries and are available without
importing host implementations. This increment adds no expression syntax: making,
reading, and updating a record are ordinary typed, graph-visible node calls.

## Declaring schemas

```python
from kohakunode import NodeLibrary

geometry = NodeLibrary("geometry")
point = geometry.record(
    "Point",
    [("x", float), ("y", float, 0.0), ("label", "str?", None), ("tags", "list[str]", [])],
)
```

Nominal identity is `geometry.Point`, independent of import alias or Python class
name. Another library's `Point` is different even with equal fields. Lower-level
APIs are `RecordField(name, type, has_default, default)`,
`RecordSchema(name, fields, schema_id="")`, and `Library.add_record(schema)` (or
`add_record(name, fields)`). Registration returns the immutable canonical schema.

Fields are ordered and required unless they have defaults. `None` as a default is
not absence. Defaults are validated and deeply frozen when the schema is created;
mutating the original default container cannot change the contract.

A record library exports signature format 2; node-only libraries still export
format 1 unchanged. Both are readable. Example format 2:

```json
{
  "kirsig": 2,
  "library": "geometry",
  "nodes": [],
  "records": [{
    "name": "Point",
    "fields": [
      {"name": "x", "type": "float"},
      {"name": "y", "type": "float", "default": 0.0},
      {"name": "label", "type": "str?", "default": null}
    ]
  }]
}
```

`nodes` contains handwritten host signatures only. Generated operations are derived
from schemas, not separately editable serialized signatures. Field `type` is always
required, including `_`. Unknown format versions are errors; older tools must
reject format 2 rather than ignore schemas. Names, fields, and generated operation
collisions are checked. Registration normalizes known local record names in host
signatures, including nodes registered before the schema.

## Explicit operations

| Operation | Inputs | Output |
|---|---|---|
| `Point.make` | schema fields with defaults | `record: geometry.Point` |
| `Point.get.x` | `record: geometry.Point` | `value: float` |
| `Point.with.x` | `record: geometry.Point`, `value: float` | `record: geometry.Point` |

```text
@use "geometry" as g
(1.0)g.Point.make(p)
(p)g.Point.get.x(x)
(p, 3.0)g.Point.with.x(q)
(q)g.Point.get.x(updated_x)
(p)g.Point.get.x(original_x)
```

The updated value is 3.0 and the original remains 1.0. Every operation has ordinary
ports and source origins. No attribute expression, reflective `getattr`, or dynamic
field-name lookup is introduced. Invalid field operations are unknown nodes;
incompatible statically known values are checker errors. Host-produced values are
also validated at runtime.

Annotations accept unaliased schema names, import aliases (`g.Point`), and canonical
IDs (`geometry.Point`). Ambiguous bare names are errors. Checking and lowering
canonicalize annotations without altering the authored program. Source modules
preserve schema identities in exported subgraph signatures.

## Fields and types

Every constructed record contains every declared field. Nullable means a field can
hold `None`, not that it can be absent. Omitted fields require defaults. Explicit
`None` never requests a default. Unknown fields are rejected.

Supported field types are `_`, `bool`, `int`, `float`, `str`, `None`, bare `list` and
`dict`, `list[T]`, `dict[str, T]`, unions, optionals, and nominal records. Integers fit
float fields; booleans are not integers. Containers are checked recursively.
Nullable/union schemas normalize to a stable serializable type representation.

A nested record must have the declared nominal identity; a dictionary does not
implicitly become a record. A union or nullable receiver does not gain common-field
projection. Use an explicit node that produces the required record type first.

Local nominal references qualify by defining library. All referenced schemas must
be loaded. Forward registration is allowed, but environment assembly rejects
missing references and cycles, including across libraries and optional/container
fields. Recursive schemas are outside this initial increment.

Defaults are finite portable JSON scalars, lists, and string-keyed dictionaries.
Nested record defaults are initially unsupported: construct nested records
explicitly. A nullable nested record can default to `None`.

## Value and alias semantics

`RecordValue` is deeply immutable. Record operations accept this representation,
not arbitrary host objects or mapping subclasses.

1. Construction snapshots mutable list/dict inputs into private immutable storage.
2. Projection of a list/dictionary returns a fresh mutable container.
3. Projection of an immutable nested record may share it safely.
4. Replacement snapshots its new input and creates a new record.
5. Container object identity/sharing is not part of record semantics. Dictionary
   fields are canonical string-keyed mappings; projection materializes keys in
   sorted order, not the insertion order of the original host dictionary.

Mutating constructor inputs or projected containers cannot change a record.
Existing `mutates` nodes may operate on those projected containers under the normal
mutation contract; in-place mutation of `RecordValue` is unsupported.

The runtime domain is exact builtin null/bool/int/finite-float/string values,
lists, string-keyed dictionaries, and nested records recursively. Cycles, opaque
resources, arbitrary objects, custom container subclasses, properties and
descriptors are rejected. Projection invokes no user accessor or copy hook.

Container construction/projection scales with the data materialized. It is not
always cheap enough to run inline on a dispatcher; ordinary worker bindings remain
available. Large opaque/reference values are separate future work.

## Host boundaries, codecs, and persistence

Helpers are available from `kohakunode.records` and the package root:

```python
from kohakunode import construct, decode_record, encode_record, project, replace_field

p = construct(point, x=1.0, tags=["input"])
q = replace_field(point, p, "x", 2.0)
assert project(point, p, "x") == 1.0
payload = encode_record(q)
restored = decode_record(payload, {point.schema_id: point})
assert restored == q
```

The explicit codec tags records as
`{"$kir": "record", "schema": id, "fields": {...}}`, lists as
`{"$kir": "list", "items": [...]}`, and dictionaries as
`{"$kir": "dict", "items": {...}}`. Scalars remain scalars. These container tags
prevent user dictionary keys from impersonating record values. Decoding receives a
canonical-ID schema registry and validates shape, tags, fields and values.

Adapters may encode/decode at their boundaries; engines need not use the reference
class internally. Application-specific object conversion remains an explicit host
operation, never an automatically pure projection.

Values and trusted operation descriptors are pickle-safe. Pickles remain trusted
inputs; use the explicit tagged data codec at untrusted boundaries. Strong
`__togeari_digest__` identity includes schema ID and field data. Its version-1
length-delimited typed encoding distinguishes scalars/containers and supports
arbitrary-size integers without changing global Python conversion limits. External
JSON encoders can impose their own integer limits; direct tagged-object roundtrip
does not.

## Identity and compatibility

Field types/defaults contribute to signature contract identity. Loaded record
libraries produce dependency manifests even without source imports (`modules: []`,
signature contracts present), preventing schema revisions from sharing cache or
snapshot keys. Legacy programs without records or source modules retain previous
hash construction.

Python/Rust signature loading, generated signatures, checker, graph/text tooling,
and WASM share the schema contract. The reference and both Togeari cores execute
ordinary generated calls; no record-specific scheduling instruction is added.
This does not imply structural subtyping, general cacheability, arbitrary object
reflection, or application-specific engine classes.
