"""Explicit ordered collection, checked against every lowering pass and both graph views."""

import json
from pathlib import Path

from kohakunode import Interpreter, compile_file, compile_program
from kohakunode.graph import from_graph, to_graph
from kohakunode.lower import PASSES, run_passes

HERE = Path(__file__).resolve().parent
EXPECTED = {"result": [3, None, 7], "rows": [[], [0, 1], [0, 1, 4]]}


def execute(program, env):
    interpreter = Interpreter(program, env)
    interpreter.run()
    return interpreter.source_values()


def main() -> None:
    compiled = compile_file(HERE / "main.kir")
    reference = execute(compiled.program, compiled.env)
    assert {key: reference[key] for key in EXPECTED} == EXPECTED
    for count in range(len(PASSES) + 1):
        lowered = run_passes(compiled.program, compiled.env, list(PASSES)[:count])
        assert execute(lowered, compiled.env) == reference
    for style in ("wires", "variables"):
        graph = to_graph(compiled.program, compiled.env, data=style)
        restored = from_graph(json.loads(json.dumps(graph)))
        rebuilt = compile_program(restored)
        assert execute(rebuilt.lowered, rebuilt.env) == reference
    print(json.dumps(EXPECTED, sort_keys=True))
    print("reference: private append and all lowering pass prefixes agree")
    print("graph: wires and variables roundtrips agree")


if __name__ == "__main__":
    main()
