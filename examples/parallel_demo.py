"""Parallel execution example."""

from pathlib import Path

from kohakunode import Executor, Registry

reg = Registry()
reg.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
reg.register("print", lambda v: print(f"  {v}"), output_names=[])

print("Parallel demo:")
exe = Executor(registry=reg)
exe.execute_file(Path(__file__).parent / "parallel_demo.kir")
