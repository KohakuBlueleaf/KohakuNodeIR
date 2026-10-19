"""Record KIR v1 interpreter results on every v1 .kir file.

Usage: python record_v1.py <v1_repo> <out_dir>

For each .kir under examples/ and tests/fixtures/ (error fixtures excluded)
this writes <out_dir>/<rel>.kir (the source) and <out_dir>/<rel>.json with the
status, captured stdout and final variable store. Functions outside FUNCS get a
deterministic stub whose output spells out its call (name and arguments), so
the recorded values witness the data flow. Every node call counts against
STEP_BUDGET, so a non-terminating program is recorded as such.
"""

import contextlib
import inspect
import io
import json
import shutil
import sys
from pathlib import Path

from kohakunode.ast.nodes import FuncCall, KeywordArg, SubgraphDef

from kohakunode import Executor, Registry, parse

STEP_BUDGET = 100_000
BUILTINS = {"branch", "switch", "jump", "parallel"}

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


class StepBudgetExceeded(Exception):
    pass


def stub(name, n_out):
    def call(**kwargs):
        args = ", ".join(f"{k}={kwargs[k]!r}" for k in sorted(kwargs))
        if n_out <= 1:
            return f"{name}({args})"
        return tuple(f"{name}#{i}({args})" for i in range(n_out))

    return call


def walk(node):
    yield node
    for value in vars(node).values() if hasattr(node, "__dict__") else ():
        for item in value if isinstance(value, list) else [value]:
            if hasattr(item, "__dataclass_fields__"):
                yield from walk(item)


def call_sites(program):
    """name -> (max positional count, keyword names, max output count) over all call sites."""
    sites = {}
    for node in walk(program):
        if isinstance(node, FuncCall):
            pos = sum(1 for i in node.inputs if not isinstance(i, KeywordArg))
            kws = {i.name for i in node.inputs if isinstance(i, KeywordArg)}
            p, k, o = sites.get(node.func_name, (0, set(), 0))
            sites[node.func_name] = (max(p, pos), k | kws, max(o, len(node.outputs)))
    return sites


def make_registry(stubs):
    reg = Registry()
    steps = [0]

    def counted(fn):
        def call(*args, **kwargs):
            steps[0] += 1
            if steps[0] > STEP_BUDGET:
                raise StepBudgetExceeded(f"more than {STEP_BUDGET} node calls")
            return fn(*args, **kwargs)

        call.__signature__ = inspect.signature(fn)
        return call

    for name, (fn, outs) in FUNCS.items():
        reg.register(name, counted(fn), output_names=outs)
    for name, (n_pos, kws, n_out) in stubs.items():
        reg.register(
            name,
            counted(stub(name, n_out)),
            output_names=[f"out{i}" for i in range(n_out)],
            input_names=[f"in{i}" for i in range(n_pos)] + sorted(kws),
            defaults={},
        )
    return reg


def jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return {"repr": repr(value)}


def record_file(path):
    try:
        program = parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "parse_error", "error": f"{type(exc).__name__}: {exc}"}
    defined = {s.name for s in program.body if isinstance(s, SubgraphDef)}
    stubs = {
        n: s for n, s in call_sites(program).items() if n not in FUNCS.keys() | defined | BUILTINS
    }
    record = {"stubs": sorted(stubs)}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            store = Executor(registry=make_registry(stubs), validate=False).execute_file(path)
    except StepBudgetExceeded as exc:
        return record | {"status": "nonterminating", "error": str(exc)}
    except Exception as exc:
        return record | {
            "status": "error",
            "stdout": buf.getvalue(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    snapshot = {k: jsonable(v) for k, v in sorted(store.snapshot().items())}
    return record | {"status": "ok", "stdout": buf.getvalue(), "vars": snapshot}


def main(repo, out):
    repo, out = Path(repo), Path(out)
    files = sorted(
        p
        for root in ("examples", "tests/fixtures")
        for p in (repo / root).rglob("*.kir")
        if "errors" not in p.parts
    )
    counts = {}
    for path in files:
        rel = path.relative_to(repo)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        record = {"file": rel.as_posix()} | record_file(path)
        target.with_suffix(".json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        counts[record["status"]] = counts.get(record["status"], 0) + 1
        print(f"{record['status']:15s} {rel.as_posix()} {record.get('error', '')}")
    print(counts)


if __name__ == "__main__":
    main(*sys.argv[1:3])
