"""The Python reference reproduces tests/corpus/golden byte for byte (the Rust core must too)."""

import json
from pathlib import Path

import pytest

from kohakunode import compile_program, parse, write
from kohakunode.graph import to_graph
from kohakunode.sig import library_from_json
from kohakunode.sig.env import build_env

CASES = Path(__file__).parent / "corpus" / "golden" / "cases"


def golden(d: Path, name: str) -> str:
    return (d / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir()))
def test_golden(case):
    d = CASES / case
    lib = library_from_json(json.loads(golden(d, "sig.kirsig.json")))
    program = parse(golden(d, "input.kir"))
    compiled = compile_program(program, [lib])
    graph = to_graph(program, build_env(program, [lib]))
    assert write(program) == golden(d, "canonical.kir")
    assert write(compiled.lowered) == golden(d, "lowered.kir")
    assert json.dumps(graph, indent=2, ensure_ascii=False) + "\n" == golden(d, "graph.kirgraph")
    hashes = json.loads(golden(d, "hashes.json"))
    assert (compiled.semantic_hash, compiled.full_hash) == (hashes["semantic"], hashes["full"])
