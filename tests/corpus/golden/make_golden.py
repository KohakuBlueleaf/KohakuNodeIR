"""Regenerate the golden outputs: python tests/corpus/golden/make_golden.py

Each case directory holds the input ``input.kir``, the signatures it is
checked against ``sig.kirsig.json``, and what the Python reference produces:
``canonical.kir`` (the program as written, canonical form), ``lowered.kir``
(after every optimization pass), ``graph.kirgraph`` and
``graph.variables.kirgraph`` (the graph view, data as wires / as variables) and
``hashes.json``.
Cases come from the v1 corpus (files v1 ran cleanly) and ``v2/*.kir``.
"""

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
TESTS = HERE.parent.parent
sys.path.insert(0, str(TESTS))

from kohakunode import compile_program, parse, write  # noqa: E402
from kohakunode.graph import to_graph  # noqa: E402
from kohakunode.sig import library_from_json, library_to_json  # noqa: E402
from kohakunode.sig.env import build_env  # noqa: E402
from kohakunode.sig.model import Library, Port, Signature  # noqa: E402
from test_v1_parity import EXPECTED, library_for  # noqa: E402

V1 = TESTS / "corpus" / "v1"
V2 = HERE / "v2"


def sources():
    for path in sorted(V1.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "ok" and EXPECTED.get(record["file"], ("",))[0] != "rejected":
            yield "v1__" + record["file"].replace("/", "__").removesuffix(".kir"), path.with_suffix(
                ".kir"
            )
    for path in sorted(V2.glob("*.kir")):
        yield "v2__" + path.stem, path


def outputs(src: str, lib) -> dict[str, str]:
    program = parse(src)
    compiled = compile_program(program, [lib])
    env = build_env(program, [lib])
    return {
        "canonical.kir": write(program),
        "lowered.kir": write(compiled.lowered),
        "graph.kirgraph": _json(to_graph(program, env)),
        "graph.variables.kirgraph": _json(to_graph(program, env, "variables")),
        "hashes.json": json.dumps(
            {"semantic": compiled.semantic_hash, "full": compiled.full_hash}, indent=2
        )
        + "\n",
    }


def main() -> None:
    cases = HERE / "cases"
    if cases.exists():
        shutil.rmtree(cases)
    for name, path in sources():
        src = path.read_text(encoding="utf-8")
        sig = library_to_json(_json_safe(library_for(parse(src))))
        d = cases / name
        d.mkdir(parents=True)
        (d / "input.kir").write_text(src, encoding="utf-8")
        (d / "sig.kirsig.json").write_text(json.dumps(sig, indent=2) + "\n", encoding="utf-8")
        for fname, text in outputs(src, library_from_json(sig)).items():
            (d / fname).write_text(text, encoding="utf-8")
    print(f"wrote {len(list(cases.iterdir()))} cases")


def _json(graph: dict) -> str:
    return json.dumps(graph, indent=2, ensure_ascii=False) + "\n"


def _json_safe(lib):
    """Stub inputs use a non-JSON 'absent' default; a signature file marks them optional with null."""
    out = Library(lib.name)
    for sig in lib.signatures.values():
        ins = tuple(Port(p.name, p.type, None) if not p.required else p for p in sig.inputs)
        out.add_signature(Signature(sig.name, ins, sig.outputs, sig.mutates, sig.ordered, sig.doc))
    return out


if __name__ == "__main__":
    main()
