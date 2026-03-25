"""Branching example: nested if/else classification."""

from pathlib import Path

from kohakunode import Executor, Registry

if __name__ == "__main__":
    reg = Registry()
    reg.register("less_than", lambda a, b: a < b, output_names=["result"])
    reg.register("greater_than", lambda a, b: a > b, output_names=["result"])
    reg.register("print", lambda v: print(f"  {v}"), output_names=[])

    print("Classifying value=42:")
    exe = Executor(registry=reg)
    exe.execute_file(Path(__file__).parent / "branching.kir")
