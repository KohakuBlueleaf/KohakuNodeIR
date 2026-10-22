"""Run linked source and its lowering, then show the two imported call-site origins."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from module_demo_nodes import LIB  # noqa: E402

from kohakunode import Interpreter, compile_file  # noqa: E402
from kohakunode.syntax.ast import Call, walk  # noqa: E402


def main() -> None:
    compiled = compile_file(HERE / "main.kir", [LIB])
    reference = Interpreter(compiled.program, compiled.env)
    reference.run()
    lowered = Interpreter(compiled.lowered, compiled.env)
    lowered.run()
    expected = {"first": ["primary:2", "primary:4"], "second": ["backup:2", "backup:4"]}
    assert reference.source_values() == lowered.source_values() == expected
    print(json.dumps(expected, sort_keys=True))
    print("reference: linked and lowered results match")
    origins = [
        stmt.origin
        for stmt in walk(compiled.lowered.body)
        if isinstance(stmt, Call) and stmt.origin.definition == "decorate"
    ]
    assert len(origins) == 2
    assert origins[0].node_id == origins[1].node_id
    assert origins[0].calls != origins[1].calls
    print("origins: same definition node, two distinct call-site chains")
    for origin in origins:
        print(json.dumps(asdict(origin), sort_keys=True))


if __name__ == "__main__":
    main()
