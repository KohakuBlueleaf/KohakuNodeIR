"""ComfyUI workflow → KirGraph → KIR conversion demo.

Reads example_workflow.json, converts it to .kirgraph and L2 KIR,
and prints both outputs.
"""

import json
from pathlib import Path

from kohakunode_utils.comfyui import comfyui_to_kirgraph
from kohakunode_utils.comfyui_to_kir import comfyui_to_kir

HERE = Path(__file__).parent

# ── Load ComfyUI workflow ──
workflow_path = HERE / "example_workflow.json"
workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
print("=" * 60)
print(f"ComfyUI workflow: {workflow_path.name}")
print(f"  {len(workflow['nodes'])} nodes, {len(workflow['links'])} links")
print("=" * 60)

# ── Convert to KirGraph (L1) ──
print("\n" + "=" * 60)
print("KirGraph (L1)")
print("=" * 60)
graph = comfyui_to_kirgraph(workflow)
print(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges")
for n in graph.nodes:
    print(f"    {n.id:20s} type={n.type:30s} name={n.name}")

kirgraph_json = graph.to_json(indent=2)
print("\n--- .kirgraph JSON ---")
print(kirgraph_json)

# ── Convert to L2 KIR text ──
print("\n" + "=" * 60)
print("L2 KIR text")
print("=" * 60)
kir_text = comfyui_to_kir(workflow)
print(kir_text)
