# Signature-only typed records

Run from the repository root with the current checkout installed:

```sh
python examples/records/run.py
kir check examples/records/main.kir
kir run examples/records/main.kir
kir lower examples/records/main.kir
kir graph examples/records/main.kir --data wires -o records.kirgraph
kir text records.kirgraph
```

No `--lib`, application Python import or service is needed. The version-2
`geometry.kirsig.json` file has `nodes: []`: its schemas generate trusted
`make`, `get` and `with` operations when loaded. It matches the
[record specification](../../docs/spec/records.md): `Point` has required `x`,
default `y=0.0`, nullable `label=None`, and `tags: list[str]=[]`.
`Request` nests a required `Point`, an ID, tags and a nullable fallback point.
A dictionary is not an implicit `Point`; the example constructs the nested
record explicitly.

`main.kir` contains a typed `move(request: g.Request, x: float)` subgraph.
It gets the point, replaces `x`, and replaces the containing request's point.
The operations stay ordinary graph-visible calls with typed ports. The original
point remains unchanged. The expected summary is:

```text
original_x = 1.0
updated_x = 3.0
default_y = 0.0
nullable_label = None
nullable_fallback = None
original_tags = ["input"]
reviewed_tags = ["input", "reviewed"]
```

The standalone runner checks the source and every lowering pass prefix against
the reference, then roundtrips both `wires` and `variables` graphs through JSON
and recompiles them. Record `get`/`with` operations remain visible and carry
source `origin` fields in the compiled graph. Origins are separate from editor
metadata and are not new text syntax. Linked text/graphs name the portable
`geometry` library rather than its original file path; when loading those
elsewhere, supply `--sig-path examples/records` (the runner passes that directory
explicitly).

The Python portion uses only the loaded schemas to demonstrate real list alias
safety, not merely rebinding: it mutates constructor input lists, projected lists
and replacement input lists. Stored records remain unchanged. Immutable nested
records may safely be shared. Finally it roundtrips the nested value through
`encode_record`/`decode_record` and checks its stable digest.

The tagged codec distinguishes records, lists and dictionaries. These tags are
adapter data, not KIR expression syntax; printed record representations from
`kir run` are not a persistence format. Use the explicit codec when moving record
values across an adapter boundary.
