"""Mixed control flow + dataflow demo.

Shows full pipeline:
1. Load .kirgraph (L1) → compile to .kir (L2) → strip to L3 → execute
2. Load .kir (L2) → decompile to .kirgraph (L1) → recompile to L2
3. Show all 3 levels side by side
"""

from pathlib import Path

from kohakunode import DataflowCompiler, Executor, Writer, parse
from kohakunode.compiler.strip_meta import StripMetaPass
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.decompiler import KirGraphDecompiler
from kohakunode.kirgraph.schema import KirGraph

HERE = Path(__file__).parent
writer = Writer()

# =====================================================================
# Part A: .kirgraph (L1) → .kir (L2) → L3 → execute
# =====================================================================
print("=" * 70)
print("PART A: .kirgraph (L1) → .kir (L2) → L3 → Execute")
print("=" * 70)

graph_json = HERE / "mixed_example.kirgraph"
graph = KirGraph.from_json(graph_json.read_text(encoding="utf-8"))

print(f"\n--- L1: {len(graph.nodes)} nodes, {len(graph.edges)} edges ---")
for n in graph.nodes:
    ctrl = f"ctrl:[{','.join(n.ctrl_inputs)}]→[{','.join(n.ctrl_outputs)}]" if n.ctrl_inputs or n.ctrl_outputs else "no-ctrl"
    print(f"  {n.id:15s} {n.type:12s} {ctrl}")

# L1 → L2
compiler = KirGraphCompiler()
program_l2 = compiler.compile(graph)
kir_l2 = writer.write(program_l2)
print(f"\n--- L2: .kir with @dataflow: and @meta ---")
print(kir_l2)

# L2 → L3 (expand @dataflow: + strip @meta)
dc = DataflowCompiler()
program_l2b = dc.transform(program_l2)
strip = StripMetaPass()
program_l3 = strip.transform(program_l2b)
kir_l3 = writer.write(program_l3)
print(f"--- L3: .kir pure sequential (no @dataflow:, no @meta) ---")
print(kir_l3)

# Execute L3
print("--- Execute ---")
exe = Executor(validate=False)
exe.register("add", lambda a, b: a + b, output_names=["result"])
exe.register("multiply", lambda a, b: a * b, output_names=["result"])
exe.register("less_than", lambda a, b: a < b, output_names=["result"])
exe.register("to_string", lambda value: str(value), output_names=["result"])
exe.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
exe.register("print", lambda v: print(f"  OUTPUT: {v}"), output_names=[])

store = exe.execute(program_l3)

# =====================================================================
# Part B: .kir (L2) → decompile to .kirgraph (L1) → recompile to L2
# =====================================================================
print("\n" + "=" * 70)
print("PART B: .kir (L2) → .kirgraph (L1) → .kir (L2) roundtrip")
print("=" * 70)

kir_source = (HERE / "mixed_example.kir").read_text(encoding="utf-8")
program_from_kir = parse(kir_source)

print(f"\n--- Original .kir (L2) ---")
print(writer.write(program_from_kir))

# L2 → L1
decompiler = KirGraphDecompiler()
recovered_graph = decompiler.decompile(program_from_kir)

print(f"--- Decompiled to L1: {len(recovered_graph.nodes)} nodes, {len(recovered_graph.edges)} edges ---")
for n in recovered_graph.nodes:
    print(f"  {n.id:20s} type={n.type}")

# L1 → L2 again
recompiled = compiler.compile(recovered_graph)
print(f"\n--- Recompiled back to L2 ---")
print(writer.write(recompiled))

# L2 → L3
recompiled_l2b = dc.transform(recompiled)
recompiled_l3 = strip.transform(recompiled_l2b)
print(f"--- Recompiled L3 (pure sequential) ---")
print(writer.write(recompiled_l3))
