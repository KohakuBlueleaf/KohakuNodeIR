"""Mixed mode example: control flow loop + dataflow sections in one file."""

from pathlib import Path

from kohakunode import Executor, Registry

reg = Registry()
reg.register("add", lambda a, b: a + b, output_names=["result"])
reg.register("multiply", lambda a, b: a * b, output_names=["result"])
reg.register("less_than", lambda a, b: a < b, output_names=["result"])
reg.register("to_float", lambda value: float(value), output_names=["result"])
reg.register("to_string", lambda value: str(value), output_names=["result"])
reg.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
reg.register("print", lambda v: print(v), output_names=[])

exe = Executor(registry=reg)
store = exe.execute_file(Path(__file__).parent / "mixed_mode.kir")
print(f"Final total = {store.get('total')}")
