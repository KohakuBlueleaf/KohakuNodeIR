"""Check, optimize and run every example: python examples/run_examples.py"""

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from basics.nodes import LIB as BASICS  # noqa: E402
from gbc.nodes import LIB as GBC  # noqa: E402
from tour.nodes import LIB as TOUR  # noqa: E402

from kohakunode import Interpreter, compile_file  # noqa: E402

SUITES = {"basics": BASICS, "tour": TOUR, "gbc": GBC}


def main() -> int:
    failures = 0
    for folder, lib in SUITES.items():
        for path in sorted((HERE / folder).glob("*.kir")):
            print(f"== {folder}/{path.name}")
            try:
                compiled = compile_file(path, [lib])
                for d in compiled.warnings:
                    print(f"   {d}")
                interp = Interpreter(compiled.lowered, compiled.env)
                interp.run()
                values = interp.source_values()
                shown = {
                    k: v for k, v in values.items() if k in ("result", "summary", "out", "graph")
                }
                if shown:
                    print(f"   {shown}")
            except Exception as exc:  # report every example, keep going
                failures += 1
                print(f"   FAILED: {type(exc).__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
