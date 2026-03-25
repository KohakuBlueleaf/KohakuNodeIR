"""Error handling example using @try/@except.

Demonstrates:
- A function that sometimes fails (fetch).
- The @except body running as a fallback when fetch raises.
- How to pass the URL in as a pre-set variable.
- Running the same program twice: once with a failing URL, once with a
  working URL, to show both code paths.
"""

import json
from pathlib import Path

from kohakunode import Executor, Registry


def make_registry(fail: bool = True) -> Registry:
    """Build a registry; when *fail* is True, fetch() always raises."""
    reg = Registry()

    if fail:
        def fetch(url: str) -> str:
            raise ConnectionError(f"Cannot reach {url!r}")
    else:
        def fetch(url: str) -> str:
            # Simulate a successful HTTP response body
            return '{"value": 42}'

    reg.register("fetch", fetch, output_names=["result"])
    reg.register(
        "parse_json",
        lambda raw: json.loads(raw).get("value", "unknown"),
        output_names=["result"],
    )
    reg.register(
        "log_error",
        lambda msg: print(f"  [ERROR] {msg}"),
        output_names=[],
    )
    reg.register("identity", lambda v: v, output_names=["result"])
    reg.register("print", lambda v: print(f"  result = {v!r}"), output_names=[])
    return reg


if __name__ == "__main__":
    kir_path = Path(__file__).parent / "error_handling.kir"
    source = kir_path.read_text(encoding="utf-8")

    print("=== KIR Source ===")
    print(source)

    # --- Run 1: fetch fails ---
    print("=== Run 1: fetch raises (expect fallback) ===")
    reg_fail = make_registry(fail=True)
    # Pre-set the 'url' variable that the KIR file references
    exe_fail = Executor(registry=reg_fail, validate=False)
    prog = exe_fail._compiler.transform(
        __import__("kohakunode").parse(source)
    )
    exe_fail.registry = reg_fail
    # Inject 'url' via pre-seeded variable
    from kohakunode.engine.interpreter import Interpreter

    interp = Interpreter(reg_fail)
    interp.context.variables.set("url", "http://bad-host/api")
    interp.run(prog)
    store = interp.context.variables
    print(f"  result = {store.get('result')!r}")

    print()

    # --- Run 2: fetch succeeds ---
    print("=== Run 2: fetch succeeds ===")
    reg_ok = make_registry(fail=False)
    interp2 = Interpreter(reg_ok)
    interp2.context.variables.set("url", "http://good-host/api")
    interp2.run(prog)
    store2 = interp2.context.variables
    print(f"  result = {store2.get('result')!r}")
