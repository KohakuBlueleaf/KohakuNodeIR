"""Hello World — simplest possible KIR program."""

from pathlib import Path

from kohakunode import Executor, Registry

if __name__ == "__main__":
    reg = Registry()
    reg.register("print", lambda v: print(v), output_names=[])

    exe = Executor(registry=reg)
    exe.execute_file(Path(__file__).parent / "hello_world.kir")
