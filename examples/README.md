# Examples

Run them all (check, run every optimization pass, run on the reference interpreter):

```
python examples/run_examples.py
```

| Folder | Contents |
|---|---|
| `basics/` | v1's basic programs, unchanged, with the node library they call (`basics/nodes.py`) |
| `tour/` | One file per v2 feature: `each`, `@try` / `@except err`, typed `@def` with `@hint`, `@dataflow` with a `mutates` node |
| `gbc/` | Graph-Based Captioning for one image as one sequential job, with stand-in nodes |
| `comfyui/` | A ComfyUI UI workflow and an API prompt, for `kohakunode.comfyui` |
| [`modules/`](modules/README.md) | Imported KIR library with branch + `each`, two call sites, lightweight hosts and source-origin sidecars; run separately with `python examples/modules/run.py` |
| [`records/`](records/README.md) | Signature-only nested `Request`/`Point` records, explicit field operations, list alias safety and reference/lowering/graph equivalence; run separately with `python examples/records/run.py` |

Any of them works with the CLI too, for example:

```
kir lower examples/gbc/gbc.kir --lib examples.gbc.nodes
kir graph examples/tour/01_each.kir --lib examples.tour.nodes -o each.kirgraph
```

(`--lib` imports a Python module; run from the repository root so `examples` is importable.)
