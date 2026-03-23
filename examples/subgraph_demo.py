"""Subgraph example: define and reuse a custom node group."""

from pathlib import Path

from kohakunode import Executor

exe = Executor()
exe.register("min_val", lambda a, b: min(a, b), output_names=["result"])
exe.register("max_val", lambda a, b: max(a, b), output_names=["result"])
exe.register("add", lambda a, b: a + b, output_names=["result"])
exe.register("divide", lambda a, b: a / b, output_names=["result"])
exe.register("print_val", lambda v: print(f"  Result: {v}"), output_names=[])

print("Running subgraph demo:")
kir_path = Path(__file__).parent / "subgraph_demo.kir"
exe.execute_file(kir_path)
