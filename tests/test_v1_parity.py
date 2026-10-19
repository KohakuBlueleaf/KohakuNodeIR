"""v2 must reproduce what v1 did on every v1 program that ran cleanly (tests/corpus/v1)."""

import contextlib
import io
import json
from pathlib import Path

import pytest

from kohakunode import (
    Interpreter,
    KirCheckError,
    KirRuntimeError,
    NodeLibrary,
    compile_program,
    parse,
)
from kohakunode.sig.model import Port, Signature
from kohakunode.syntax.ast import Call, Def, walk

CORPUS = Path(__file__).parent / "corpus" / "v1"

# The functions tests/corpus/v1/recorder/record_v1.py gave v1.
FUNCS = {
    "add": (lambda a, b: a + b, ["result"]),
    "subtract": (lambda a, b: a - b, ["result"]),
    "multiply": (lambda a, b: a * b, ["result"]),
    "divide": (lambda a, b: a / b if b != 0 else 0, ["result"]),
    "min_val": (lambda a, b: min(a, b), ["result"]),
    "max_val": (lambda a, b: max(a, b), ["result"]),
    "less_than": (lambda a, b: a < b, ["result"]),
    "less_equal": (lambda a, b: a <= b, ["result"]),
    "greater_than": (lambda a, b: a > b, ["result"]),
    "equal": (lambda a, b: a == b, ["result"]),
    "to_int": (lambda v: int(v), ["result"]),
    "to_float": (lambda v: float(v), ["result"]),
    "to_string": (lambda v: str(v), ["result"]),
    "concat": (lambda a, b: str(a) + str(b), ["result"]),
    "format_string": (lambda t, v: str(t).format(v), ["result"]),
    "format_factorial": (lambda n, r: f"{n}! = {r}", ["result"]),
    "print": (lambda v: print(v), []),
    "print_val": (lambda v: print(v), []),
    "log": (lambda v: print(f"[log] {v}"), []),
    "identity": (lambda v: v, ["result"]),
}

ABSENT = object()


def stub(name, n_out):
    def call(**kwargs):
        given = {k: v for k, v in kwargs.items() if v is not ABSENT}
        args = ", ".join(f"{k}={given[k]!r}" for k in sorted(given))
        if n_out <= 1:
            return f"{name}({args})"
        return tuple(f"{name}#{i}({args})" for i in range(n_out))

    return call


def library_for(program) -> NodeLibrary:
    lib = NodeLibrary("v1")
    for name, (fn, outs) in FUNCS.items():
        lib.add(name, fn, outputs=outs)
    defined = {s.name for s in walk(program.body) if isinstance(s, Def)}
    aliases = {u.alias for u in program.uses if u.alias}
    sites: dict[str, tuple[int, set, int]] = {}
    for s in walk(program.body):
        if isinstance(s, Call) and s.name not in FUNCS and s.name not in defined:
            head, _, rest = s.name.partition(".")
            name = rest if head in aliases and rest else s.name
            if name in FUNCS:
                continue
            pos = sum(1 for a in s.args if a.key is None)
            kws = {a.key for a in s.args if a.key is not None}
            p, k, o = sites.get(name, (0, set(), 0))
            sites[name] = (max(p, pos), k | kws, max(o, len(s.outs)))
    for name, (n_pos, kws, n_out) in sites.items():
        names = [f"in{i}" for i in range(n_pos)] + sorted(kws)
        sig = Signature(
            name,
            tuple(Port(n, default=ABSENT) for n in names),
            tuple(Port(f"out{i}") for i in range(n_out)),
        )
        lib.add_signature(sig, stub(name, n_out))
    return lib


def jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return {"repr": repr(value)}


def cases():
    for path in sorted(CORPUS.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "ok":
            yield pytest.param(path.with_suffix(".kir"), record, id=record["file"])


# v1 behaviour v2 changes on purpose, with what v2 does instead.
EXPECTED = {
    # v1 ran @def bodies in the caller's variables, so their params and
    # internal names leaked into the top-level store; v2 keeps them inside.
    "examples/kir_basics/subgraph_demo.kir": ("def-scope", None),
    # The v1 optimizer emitted `__par_0` labels; v2 reserves `__`.
    "examples/optimizer/all_optimized_par.kir": ("rejected", "E013"),
    # Reads `url`, which nothing writes; v1 failed inside @try and ran the
    # except branch, v2 rejects the read before running.
    "examples/try_except/error_handling.kir": ("rejected", "E020"),
    "examples/try_except/error_handling_parsed.kir": ("rejected", "E020"),
    # v1 resumed a block at a stale position after a namespace re-entered by
    # `jump` from a nested block, so these loops stopped after two passes. v2
    # continues after the namespace definition, as the spec says.
    "examples/kirgraph_pipeline/compiled_l2.kir": ("stdout", "Sum of squares = 9\n"),
    "examples/kirgraph_pipeline/compiled_l3.kir": ("stdout", "Sum of squares = 9\n"),
    # Same v1 quirk; the program never updates its counter, so under v2 it loops.
    "examples/editor/mixed_mode-editor.kir": ("nonterminating", None),
    "examples/editor/mixed_mode-editor-local.kir": ("nonterminating", None),
}


@pytest.mark.parametrize("path, record", list(cases()))
def test_v1_parity(path, record):
    program = parse(path.read_text(encoding="utf-8"))
    lib = library_for(program)
    reason, detail = EXPECTED.get(record["file"], (None, None))
    if reason == "rejected":
        with pytest.raises(KirCheckError) as exc:
            compile_program(program, [lib])
        assert {d.code for d in exc.value.diagnostics if d.severity == "error"} == {detail}
        return
    compiled = compile_program(program, [lib])
    buf = io.StringIO()
    interp = Interpreter(compiled.lowered, compiled.env, step_budget=100_000)
    if reason == "nonterminating":
        with pytest.raises(KirRuntimeError, match="node calls"), contextlib.redirect_stdout(buf):
            interp.run()
        return
    with contextlib.redirect_stdout(buf):
        interp.run()
    if reason == "stdout":
        assert buf.getvalue() == detail
        return
    assert buf.getvalue() == record["stdout"]
    values = {k: jsonable(v) for k, v in interp.source_values().items()}
    if reason == "def-scope":
        expected = {k: v for k, v in record["vars"].items() if k in values}
    else:
        expected = record["vars"]
    assert values == expected
