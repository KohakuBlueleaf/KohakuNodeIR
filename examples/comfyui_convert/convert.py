"""ComfyUI workflow -> KirGraph -> KIR conversion demo.

Reads example_workflow.json, converts to .kirgraph and L2 KIR,
saves output files and prints results.
"""

import json
from pathlib import Path

from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.compiler.strip_meta import StripMetaPass
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.serializer.writer import Writer
from kohakunode_utils.comfyui import comfyui_to_kirgraph
from kohakunode_utils.comfyui_to_kir import comfyui_to_kir

HERE = Path(__file__).parent
writer = Writer()

# ── Load ComfyUI workflow ──
workflow_path = HERE / "example_workflow.json"
workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
print("=" * 60)
print(f"ComfyUI workflow: {workflow_path.name}")
print(f"  {len(workflow['nodes'])} nodes, {len(workflow['links'])} links")
print("=" * 60)

# ── Convert to KirGraph (L1) ──
graph = comfyui_to_kirgraph(workflow)
kirgraph_json = graph.to_json(indent=2)
(HERE / "converted.kirgraph").write_text(kirgraph_json, encoding="utf-8")
print(f"\nL1: converted.kirgraph ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
for n in graph.nodes:
    print(f"  {n.id:20s} {n.type:30s} {n.name}")

# ── Compile to L2 KIR ──
compiler = KirGraphCompiler()
prog_l2 = compiler.compile(graph)
kir_l2 = writer.write(prog_l2)
(HERE / "converted_l2.kir").write_text(kir_l2, encoding="utf-8")
print(f"\nL2: converted_l2.kir")
print(kir_l2)

# ── Compile to L3 KIR ──
dc = DataflowCompiler()
prog_l2b = dc.transform(prog_l2)
strip = StripMetaPass()
prog_l3 = strip.transform(prog_l2b)
kir_l3 = writer.write(prog_l3)
(HERE / "converted_l3.kir").write_text(kir_l3, encoding="utf-8")
print(f"L3: converted_l3.kir")
print(kir_l3)

print(f"\nFiles saved to: {HERE}")
