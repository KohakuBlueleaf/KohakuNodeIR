"""Run all basic KIR examples in this directory."""

from pathlib import Path

from kohakunode import Executor, Registry

HERE = Path(__file__).parent


def make_registry():
    reg = Registry()
    # arithmetic
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("subtract", lambda a, b: a - b, output_names=["result"])
    reg.register("multiply", lambda a, b: a * b, output_names=["result"])
    reg.register("divide", lambda a, b: a / b if b != 0 else 0, output_names=["result"])
    reg.register("min_val", lambda a, b: min(a, b), output_names=["result"])
    reg.register("max_val", lambda a, b: max(a, b), output_names=["result"])
    # comparison
    reg.register("less_than", lambda a, b: a < b, output_names=["result"])
    reg.register("less_equal", lambda a, b: a <= b, output_names=["result"])
    reg.register("greater_than", lambda a, b: a > b, output_names=["result"])
    reg.register("equal", lambda a, b: a == b, output_names=["result"])
    # conversion
    reg.register("to_int", lambda v: int(v), output_names=["result"])
    reg.register("to_float", lambda v: float(v), output_names=["result"])
    reg.register("to_string", lambda v: str(v), output_names=["result"])
    # string
    reg.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
    reg.register("format_string", lambda t, v: str(t).format(v), output_names=["result"])
    reg.register("format_factorial", lambda n, r: f"{n}! = {r}", output_names=["result"])
    # output — two aliases used across examples
    reg.register("print", lambda v: print(f"    {v}"), output_names=[])
    reg.register("print_val", lambda v: print(f"    {v}"), output_names=[])
    # data pipeline helpers
    reg.register(
        "load_csv",
        lambda path: (print(f"    [load_csv] {path}"), list(range(200)))[1],
        output_names=["data"],
    )
    reg.register(
        "clean_data",
        lambda data: [x for x in data if x >= 0],
        output_names=["cleaned"],
    )
    reg.register(
        "filter_outliers",
        lambda data, threshold=0.5: data[: int(len(data) * threshold)],
        output_names=["filtered"],
    )
    reg.register(
        "compute_stats",
        lambda data: (
            sum(data) / len(data) if data else 0,
            (sum((x - sum(data) / len(data)) ** 2 for x in data) / len(data)) ** 0.5
            if data
            else 0,
            len(data),
        ),
        output_names=["mean", "std", "count"],
    )
    reg.register(
        "normalize",
        lambda data, mean, std: [(x - mean) / std for x in data] if std else data,
        output_names=["normalized"],
    )
    reg.register(
        "save_csv",
        lambda data, path: print(f"    [save_csv] {len(data)} rows → {path}"),
        output_names=[],
    )
    # misc
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
