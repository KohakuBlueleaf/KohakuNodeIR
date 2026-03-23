"""Control flow example: factorial with loops and branches."""

from pathlib import Path

from kohakunode import Executor

exe = Executor()
exe.register("add", lambda a, b: a + b, output_names=["result"])
exe.register("multiply", lambda a, b: a * b, output_names=["result"])
exe.register("less_equal", lambda a, b: a <= b, output_names=["result"])
exe.register(
    "format_factorial",
    lambda n, r: f"{n}! = {r}",
    output_names=["result"],
)
exe.register("print_val", lambda v: print(v), output_names=[])

kir_path = Path(__file__).parent / "control_flow.kir"
store = exe.execute_file(kir_path)

print(f"\nFinal state: n={store.get('n')}, result={store.get('result')}")
