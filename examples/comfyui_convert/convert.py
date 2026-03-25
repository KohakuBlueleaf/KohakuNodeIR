"""ComfyUI workflow -> KirGraph -> KIR conversion demo.

Converts ALL example_workflow*.json files, saves outputs for each.
"""

import json
from pathlib import Path

from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.compiler.strip_meta import StripMetaPass
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.serializer.writer import Writer
from kohakunode_utils.comfyui import comfyui_to_kirgraph

HERE = Path(__file__).parent
writer = Writer()
compiler = KirGraphCompiler()
dc = DataflowCompiler()
strip = StripMetaPass()


def convert_workflow(path: Path, prefix: str) -> None:
    """Convert one ComfyUI workflow file, save all outputs."""
    raw = json.loads(path.read_text(encoding="utf-8"))

    # Detect format
    if "nodes" in raw and isinstance(raw["nodes"], list):
        node_count = len(raw["nodes"])
        link_count = len(raw.get("links", []))
        fmt = "workflow"
    else:
        node_count = len(raw)
        link_count = sum(
            1
            for v in raw.values()
            if isinstance(v, dict)
            for inp_v in v.get("inputs", {}).values()
            if isinstance(inp_v, list) and len(inp_v) == 2
        )
        fmt = "api"

    print("=" * 60)
    print(f"{path.name} ({fmt} format, {node_count} nodes, {link_count} links)")
    print("=" * 60)

    # L1: kirgraph
    graph = comfyui_to_kirgraph(raw)
    kg_json = graph.to_json(indent=2)
    out_kg = HERE / f"{prefix}.kirgraph"
    out_kg.write_text(kg_json, encoding="utf-8")
    print(f"\nL1: {out_kg.name} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
    for n in graph.nodes:
        print(f"  {n.id:25s} {n.type}")

    # L2: kir with @dataflow + @meta
    prog_l2 = compiler.compile(graph)
    kir_l2 = writer.write(prog_l2)
    out_l2 = HERE / f"{prefix}_l2.kir"
    out_l2.write_text(kir_l2, encoding="utf-8")
    print(f"\nL2: {out_l2.name}")
    print(kir_l2)

    # L3: pure sequential
    prog_l2b = dc.transform(prog_l2)
    prog_l3 = strip.transform(prog_l2b)
    kir_l3 = writer.write(prog_l3)
    out_l3 = HERE / f"{prefix}_l3.kir"
    out_l3.write_text(kir_l3, encoding="utf-8")
    print(f"L3: {out_l3.name}")
    print(kir_l3)
    print()


if __name__ == "__main__":
    # Convert all workflows
    convert_workflow(HERE / "example_workflow.json", "converted")
    convert_workflow(HERE / "example_workflow2.json", "converted2")
    convert_workflow(HERE / "example_workflow2-api.json", "converted2_api")

    print(f"All files saved to: {HERE}")
