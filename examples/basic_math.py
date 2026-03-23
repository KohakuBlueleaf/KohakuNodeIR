"""Basic math example: register simple functions and run a .kir file."""

from pathlib import Path

from kohakunode import Executor

exe = Executor()
exe.register("add", lambda a, b: a + b, output_names=["result"])
exe.register("multiply", lambda a, b: a * b, output_names=["result"])
exe.register("print_val", lambda v: print(f"Result: {v}"), output_names=[])

kir_path = Path(__file__).parent / "basic_math.kir"
store = exe.execute_file(kir_path)

print(f"\nFinal variable state:")
print(f"  x = {store.get('x')}")
print(f"  y = {store.get('y')}")
print(f"  sum = {store.get('sum')}")
print(f"  product = {store.get('product')}")
