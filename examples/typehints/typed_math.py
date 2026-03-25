"""Typed math example.

Demonstrates:
1. Registering functions with explicit output_names.
2. Loading a .kir file that uses @typehint declarations.
3. Running TypeCheckPass before execution to validate types.
4. Executing the program and inspecting final variables.
"""

from pathlib import Path

from kohakunode import Executor, Registry, Writer, parse
from kohakunode.compiler.type_check import TypeCheckPass


def make_registry() -> Registry:
    reg = Registry()
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("multiply", lambda a, b: a * b, output_names=["result"])
    reg.register("to_string", lambda v: str(v), output_names=["result"])
    reg.register("print", lambda v: print(f"  output: {v}"), output_names=[])
    return reg


if __name__ == "__main__":
    kir_path = Path(__file__).parent / "typed_math.kir"
    source = kir_path.read_text(encoding="utf-8")

    print("=== KIR Source ===")
    print(source)

    # Parse the program
    prog = parse(source)

    # Show detected typehints
    print("=== Detected @typehint entries ===")
    if prog.typehints:
        for entry in prog.typehints:
            in_types = ", ".join(t.name for t in entry.input_types)
            out_types = ", ".join(t.name for t in entry.output_types)
            print(f"  ({in_types}){entry.func_name}({out_types})")
    else:
        print("  (none)")

    # Run type check pass (validates types before execution)
    print("\n=== Running TypeCheckPass ===")
    try:
        TypeCheckPass().transform(prog)
        print("  Type check passed.")
    except Exception as exc:
        print(f"  Type check FAILED: {exc}")

    # Execute
    print("\n=== Executing ===")
    reg = make_registry()
    exe = Executor(registry=reg, validate=False)
    store = exe.execute(prog)

    print("\n=== Final variable state ===")
    print(f"  x       = {store.get('x')}")
    print(f"  y       = {store.get('y')}")
    print(f"  sum     = {store.get('sum')}")
    print(f"  product = {store.get('product')}")
    print(f"  text    = {store.get('text')!r}")
