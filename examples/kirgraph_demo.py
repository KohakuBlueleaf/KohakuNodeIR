"""KirGraph demo: Load .kirgraph JSON, compile L1->L2->L3, execute."""

from pathlib import Path

from kohakunode import DataflowCompiler, Executor, Writer
from kohakunode.compiler.strip_meta import StripMetaPass
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.schema import KirGraph

# -----------------------------------------------------------------------
# 1. Load the .kirgraph JSON (Level 1)
# -----------------------------------------------------------------------

json_path = Path(__file__).parent / "kirgraph_example.json"
graph = KirGraph.from_json(json_path.read_text(encoding="utf-8"))

print("=== Level 1: .kirgraph (node/edge topology) ===")
print(f"  Nodes: {[n.id for n in graph.nodes]}")
print(f"  Edges: {len(graph.edges)} total")
print()

# -----------------------------------------------------------------------
# 2. Compile L1 -> L2 KIR (human-readable, with @dataflow: and @meta)
# -----------------------------------------------------------------------

compiler = KirGraphCompiler()
program_l2 = compiler.compile(graph)

writer = Writer()
kir_l2_text = writer.write(program_l2)

print("=== Level 2: .kir (with @dataflow: and @meta) ===")
print(kir_l2_text)

# -----------------------------------------------------------------------
# 3. Compile L2 -> L3 KIR (pure sequential, engine-ready)
# -----------------------------------------------------------------------

dc = DataflowCompiler()
program_l2b = dc.transform(program_l2)
strip = StripMetaPass()
program_l3 = strip.transform(program_l2b)

kir_l3_text = writer.write(program_l3)

print("=== Level 3: .kir (pure sequential, no @meta) ===")
print(kir_l3_text)

# -----------------------------------------------------------------------
# 4. Execute L3
# -----------------------------------------------------------------------

print("=== Execution ===")
exe = Executor(validate=False)

# Register all node types used in the example
exe.register("add", lambda a, b: a + b, output_names=["result"])
exe.register("subtract", lambda a, b: a - b, output_names=["result"])
exe.register("multiply", lambda a, b: a * b, output_names=["result"])
exe.register("divide", lambda a, b: a / b if b != 0 else 0, output_names=["result"])
exe.register("greater_than", lambda a, b: a > b, output_names=["result"])
exe.register("less_than", lambda a, b: a < b, output_names=["result"])
exe.register("equal", lambda a, b: a == b, output_names=["result"])
exe.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
exe.register(
    "format_string",
    lambda template, value: str(template).format(value),
    output_names=["result"],
)
exe.register("to_int", lambda value: int(value), output_names=["result"])
exe.register("to_float", lambda value: float(value), output_names=["result"])
exe.register("to_string", lambda value: str(value), output_names=["result"])
exe.register("print", lambda v: print(f"  Output: {v}"), output_names=[])

store = exe.execute(program_l3)
print(f"\n  Final variables: { {k: v for k, v in store.snapshot().items()} }")
