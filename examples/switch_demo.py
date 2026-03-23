"""Switch/case example."""

from pathlib import Path

from kohakunode import Executor, Registry

reg = Registry()
reg.register("print", lambda v: print(f"  {v}"), output_names=[])

print("Switch demo (day=3):")
exe = Executor(registry=reg)
exe.execute_file(Path(__file__).parent / "switch_demo.kir")
