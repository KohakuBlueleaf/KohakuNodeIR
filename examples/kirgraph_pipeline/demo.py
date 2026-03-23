"""KirGraph pipeline demo.

Reads source.kirgraph (L1), compiles through all levels, saves outputs:
  source.kirgraph      → L1 (input)
  compiled_l2.kir      → L2 (with @dataflow:, @meta)
  compiled_l3.kir      → L3 (pure sequential, no @meta)
  decompiled.kirgraph  → L1 (roundtrip from L2)

Then executes L3.
"""

import json
from pathlib import Path

from kohakunode import DataflowCompiler, Executor, Writer, parse
from kohakunode.compiler.strip_meta import StripMetaPass
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.decompiler import KirGraphDecompiler
from kohakunode.kirgraph.schema import KirGraph

HERE = Path(__file__).parent
writer = Writer()

# ── L1: Load source ──
print("=" * 60)
print("L1: source.kirgraph")
print("=" * 60)
source_path = HERE / "source.kirgraph"
graph = KirGraph.from_json(source_path.read_text(encoding="utf-8"))
print(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges")
for n in graph.nodes:
    print(f"    {n.id:15s} type={n.type}")

# ── L1 → L2: Compile ──
print("\n" + "=" * 60)
print("L2: compiled_l2.kir (with @dataflow:, @meta)")
print("=" * 60)
compiler = KirGraphCompiler()
prog_l2 = compiler.compile(graph)
kir_l2 = writer.write(prog_l2)
(HERE / "compiled_l2.kir").write_text(kir_l2, encoding="utf-8")
print(kir_l2)

# ── L2 → L3: Sanitize ──
print("=" * 60)
print("L3: compiled_l3.kir (pure sequential)")
print("=" * 60)
dc = DataflowCompiler()
prog_l2b = dc.transform(prog_l2)
strip = StripMetaPass()
prog_l3 = strip.transform(prog_l2b)
kir_l3 = writer.write(prog_l3)
(HERE / "compiled_l3.kir").write_text(kir_l3, encoding="utf-8")
print(kir_l3)

# ── L2 → L1: Decompile (roundtrip) ──
print("=" * 60)
print("Decompiled: decompiled.kirgraph (L2 -> L1 roundtrip)")
print("=" * 60)
decompiler = KirGraphDecompiler()
graph_rt = decompiler.decompile(prog_l2)
rt_json = graph_rt.to_json(indent=2)
(HERE / "decompiled.kirgraph").write_text(rt_json, encoding="utf-8")
print(f"  {len(graph_rt.nodes)} nodes, {len(graph_rt.edges)} edges")

# ── Execute L3 ──
print("\n" + "=" * 60)
print("Execute L3")
print("=" * 60)
exe = Executor(validate=False)
exe.register("add", lambda a, b: a + b, output_names=["result"])
exe.register("subtract", lambda a, b: a - b, output_names=["result"])
exe.register("multiply", lambda a, b: a * b, output_names=["result"])
exe.register("divide", lambda a, b: a / b if b != 0 else 0, output_names=["result"])
exe.register("less_than", lambda a, b: a < b, output_names=["result"])
exe.register("greater_than", lambda a, b: a > b, output_names=["result"])
exe.register("to_string", lambda v: str(v), output_names=["result"])
exe.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
exe.register("format_string", lambda t, v: str(t).format(v), output_names=["result"])
exe.register("print", lambda v: print(f"  OUTPUT: {v}"), output_names=[])
store = exe.execute(prog_l3)
print(f"\n  Files saved to: {HERE}")
