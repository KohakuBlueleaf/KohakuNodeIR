"""Run all basic KIR examples in this directory."""

from pathlib import Path

from kohakunode import Executor, Registry

HERE = Path(__file__).parent


def make_registry():
    reg = Registry()
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("subtract", lambda a, b: a - b, output_names=["result"])
    reg.register("multiply", lambda a, b: a * b, output_names=["result"])
    reg.register("divide", lambda a, b: a / b if b != 0 else 0, output_names=["result"])
    reg.register("less_than", lambda a, b: a < b, output_names=["result"])
    reg.register("less_equal", lambda a, b: a <= b, output_names=["result"])
    reg.register("greater_than", lambda a, b: a > b, output_names=["result"])
    reg.register("equal", lambda a, b: a == b, output_names=["result"])
    reg.register("to_int", lambda v: int(v), output_names=["result"])
    reg.register("to_float", lambda v: float(v), output_names=["result"])
    reg.register("to_string", lambda v: str(v), output_names=["result"])
    reg.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
    reg.register("format_string", lambda t, v: str(t).format(v), output_names=["result"])
    reg.register("print", lambda v: print(f"    {v}"), output_names=[])
    reg.register("identity", lambda v: v, output_names=["result"])
    return reg


kir_files = sorted(HERE.glob("*.kir"))
for kir in kir_files:
    print(f"── {kir.name} ──")
    try:
        reg = make_registry()
        exe = Executor(registry=reg, validate=False)
        store = exe.execute_file(kir)
        print(f"  OK ({len(store.snapshot())} vars)")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()
