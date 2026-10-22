# Imported library, two call sites

Run from the repository root with the current checkout installed:

```sh
python examples/modules/run.py
kir check examples/modules/main.kir --lib examples.modules.module_demo_nodes:LIB
kir run examples/modules/main.kir --lib examples.modules.module_demo_nodes:LIB
kir lower examples/modules/main.kir --lib examples.modules.module_demo_nodes:LIB
```

`main.kir` imports `transforms.kir` and calls its exported `transform` twice, with
`primary` and `backup` prefixes. The imported body contains `each` and a branch:
negative values are skipped; nonnegative values go through a private `decorate`
definition. `module_demo_nodes.py` supplies only two tiny host functions. Source
imports expose KIR bodies to the compiler; they do not execute Python or hide a
second interpreter behind a host call.

The runner uses `compile_file`, executes both the linked source and the lowered
program on the reference interpreter, and checks:

```text
first  = ["primary:2", "primary:4"]
second = ["backup:2", "backup:4"]
```

It then prints the actual `Stmt.origin` objects as JSON. The two copies of
`decorate` retain the same `transforms.kir` source node, line and definition, but
have different outer call-site chains from `main.kir`. This is provenance, not a
new KIR annotation: origins live on AST statements and are omitted from written
KIR text and semantic/full hashes. The graph API serializes provenance alongside
nodes in `origin` fields (and namespace provenance in `namespace_origins`),
separate from editor metadata; formatting text alone does not serialize it. Explicit editor
`@meta node_id` values may seed an origin ID; otherwise IDs use AST traversal
paths (format-stable, not stable under arbitrary source edits).

Imports resolve relative to the entry file, so this directory can be relocated
as a unit. Run the sibling Togeari repository's `examples/modules/machine.py`
for the same library pattern on both execution cores with recorded conformance.
