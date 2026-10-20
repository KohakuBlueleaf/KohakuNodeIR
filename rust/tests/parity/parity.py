"""Differential check of the Rust core (``kohakunode._rs``) against the Python reference.

Run from the repo root after ``maturin develop --release`` (see rust/README.md)::

    python rust/tests/parity/parity.py [--seeds N] [--mutations M] [--show K]

Sources: the golden corpus, programs and entry programs from ``tests/progen.py``, parser edge
snippets, and random line-level mutations of all of them. For each source it
compares parse acceptance and canonical text, checker diagnostics, every pass
prefix, both hashes, the graph view in both data styles, and graph -> text with
and without meta; plus graph literals with non-finite numbers, editor-drawn
graphs (value, get and set nodes), data style names, and `@use` resolution
against signature files on disk. Prints every difference and exits non-zero when there
is one.
"""

import argparse
import json
import random
import re
import sys
import tempfile
import warnings
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests"))

from kohakunode import _rs, compile_program, parse, write  # noqa: E402
from kohakunode.check import check  # noqa: E402
from kohakunode.errors import KirError, KirSignatureError  # noqa: E402
from kohakunode.graph import DATA_STYLES, from_graph, to_graph  # noqa: E402
from kohakunode.lower import PASSES  # noqa: E402
from kohakunode.sig import STD, library_from_json, library_to_json  # noqa: E402
from kohakunode.sig.env import build_env  # noqa: E402
from progen import LIB, entry_program, program  # noqa: E402

CASES = REPO / "tests" / "corpus" / "golden" / "cases"

# ast.literal_eval warns on unknown escapes such as "\d"; both sides keep them.
warnings.filterwarnings("ignore", category=SyntaxWarning)

SNIPPETS = [
    "(x)foo(_tmp)\n",
    "(_x)foo(y)\n",
    "y = _x\n",
    "y = Nonesuch\n",
    "@meta a=Truex=1\nx = 1\n",
    "@meta a=1b=2\nx = 1\n",
    "True = 1\n",
    "_ = 1\n",
    "x = 1\n    # c\ny = 2\n",
    "ns:\n    x = 1\n# c\n    y = 2\n",
    '@use "x" asfoo\n',
    "x: _Foo = 1\n",
    "x: None = 1\n",
    "x: list[int | str]? = []\n",
    "@metax=1\ny = 2\n",
    "    x = 1\ny = 2\n",
    "\n\n    x = 1\n",
    "x = 1)\n",
    "x = 010\n",
    "x = -0x1F\n",
    "x = 0b101\n",
    "x = 1e999\n",
    "x = {1: 'a', True: 'b', 1.0: 'c'}\n",
    "x = {[1]: 2}\n",
    "x = '\\d\\x41\\101\\u00e9'\n",
    "x = 'a\\\nb'\n",
    "x = '''a\r\nb'''\n",
    'x = """a""""\n',
    "x = 1.\n",
    "x = .5e-3\n",
    "x = 1e16\n",
    "x = 0.0001\n",
    "x = 123456789012345678901234567890\n",
    "(1, x=2, 3)f()\n",
    "done:\nx = 1\n",
    "x = 0x\n",
    "x = 5 # c\n",
    "@meta a=foo b=(x, 1, (2, y))\nx = 1\n",
    "@except:\n    x = 1\n",
    "(a,\n b)foo(c)\n",
    "x = [1,\n    2]\n",
    "ns:\n\tx = 1\n",
    "ns:\n    x = 1\n  y = 2\n",
    "(x)switch(1=>`a`, _=>`b`, _=>`c`)\na:\n    y = 1\nb:\n    y = 2\n",
    "(x)switch(y=>`a`)\na:\n    y = 1\n",
    "(xs)each(_, i, `b`)\nb:\n    (i)print_value()\n",
    "(xs)each(`b`)\n",
    "()jump(`a`, `b`)\n",
    "()parallel()\n",
    "(c)branch(`a`)\n",
    "@typehint:\n    (Image, _)crop(Image?)\n\n(1, 2)crop(x)\n",
    "@def (a: int = 1, b = c)f(o: str):\n    o = a\n\n(1)f(x)\n",
    "@try:\n    (1)f(x)\n@except e:\n    x = 2\n(x)g()\n",
    "@use 'kir.std'\n@mode dataflow\n(a)add(b)\na = 1\n",
    "@mode dataflow\n()branch(`a`, `b`)\n",
    "@dataflow:\n    (b)identity(a)\n    (a)identity(b)\n",
    "x = 1\n@meta a=1\n",
    "x = 1\n@use 'y'\n",
    "x = 'é\\u2028\\x00'\n",
    "@hint lane=2 tags=(a, b)\n(1)print_value()\n",
    "x = {'a': [1, {'b': None}], 2: (3)}\n",
    "x = \u0661\u0662\n",
    '@use "kir.std"\n(1, 2)add(x)\n(x)identity(y)\n',
    "@def (a)f(o):\n    (a)small(c)\n    (c)branch(`t`, `e`)\n    t:\n        o = 1\n"
    "    e:\n        y = 2\n\n(1)f(z)\n",
    "xs = [1]\n(xs)each(x, `b`)\nb:\n    in = 1\n()jump(`b`)\n",
    "@mode dataflow\nc = True\n(c)branch(`a`, `b`)\na:\n    x = 1\nb:\n    x = 2\n",
    "()parallel(`a`, `b`)\na:\n    x = 1\nb:\n    x = 2\n    (x)inc(y)\n(x)inc(z)\n",
    "@try:\n    (1)flaky(x)\n@except e:\n    x = 1\n@try:\n    (2)flaky(x)\n@except e:\n"
    "    x = 2\n(e)total(t)\n",
    "@def (a)f(o):\n    (a)g(o)\n\n@def (a)g(o):\n    (a)f(o)\n\n(1)f(x)\n",
    "(1)inc(x, y)\n(1, b=2)mix(z)\n(a=1)mix(w)\n(1, 2, 3)mix(v)\n(1, a=2)mix(u)\n",
    "x = '\\N{BULLET}\\N{bullet}\\N{Latin Small Letter A}\\N{NO-BREAK SPACE}'\n",
    "x = '\\N{HANGUL SYLLABLE GA}\\N{hangul syllable gag}\\N{CJK UNIFIED IDEOGRAPH-4E00}'\n",
    "x = '\\N{cjk unified ideograph-4e00}'\n",
    "x = '\\N{LATIN CAPITAL LETTER GHA}\\N{BYTE ORDER MARK}\\N{LINE FEED}\\N{NULL}'\n",
    "x = '\\N{SPACE }'\n",
    "x = '\\N{ SPACE}'\n",
    "x = '\\N{NO BREAK SPACE}'\n",
    "x = '\\N{LATIN SMALL LETTER  A}'\n",
    "x = '\\N{LATIN_SMALL_LETTER_A}'\n",
    "x = '\\N{latin small letter a\\t}'\n",
    "x = '\\N{HANGUL SYLLABLE GAGG}'\n",
    "x = '\\N{CJK UNIFIED IDEOGRAPH-0041}'\n",
    "x = '\\N{CJK UNIFIED IDEOGRAPH-4E00 }'\n",
    "x = '\\N{NOT A NAME}'\n",
    "x = '\\N{}'\n",
    "x = '\\N{SPACE'\n",
    "x = '\\NA'\n",
    "x = '\\N{LATIN SMALL LIGATURE FF}\\N{GREEK SMALL LETTER ALPHA}"
    "\\N{EMOJI MODIFIER FITZPATRICK TYPE-1-2}'\n",
    "x = '\\N{TIBETAN LETTER -A}\\N{HANGUL JUNGSEONG O-E}\\N{KANGXI RADICAL ONE}'\n",
    '@use "x" as g\n(Nonesuch, Truex)f(_tmp, _)\ny: int | None = None\n',
    '@use "x" asg\n',
    "(x)f(None)\n",
    "(x)f(_, _y, None=>`a`)\n",
    "x: None? = 1\n",
    "x: list[None] | _ = []\n",
    "@try:\n    x = 1\n@except None:\n    x = 2\n",
    "@except_x = 1\n",
    "Falsey = 1\nNone_ = Falsey\n",
    "x = 1\n    # indented comment\ny = 2\nns:\n    a = 1\n# outdented comment\n    b = 2\n",
    "\n# c\n\nx = 1\n",
    "# c\n  x = 1\n",
    "  # c\nx = 1\n",
    "\t\n  \nx = 1\n",
    "x = 1 # c\n        # deeper\ny = 2\n",
    "ns:\n    # only a comment\nx = 1\n",
    "@try:\n    # c\n    x = 1\n@except:\n# c\n    y = 2\n",
    "x = [1, # c\n  2]\n",
    "@meta pos=() size=(3,) at=(1, 2)\nx = 1\n",
    "@meta a=((),) b=((1,), (2, 3,)) c=(x,)\nx = 1\n",
    "@meta a=(,)\nx = 1\n",
    "x = -1e309\n",
    "x = 1.5e308\n",
    "x = 0\u0661\n",
    'image = "img"\nerr = {}\n(err)len(n)\n@try:\n    (image, 13)crop(c)\n    (c)entity(node)\n'
    "@except err:\n    node = None\n(err)len(m)\n",
    "e = {}\n@try:\n    (1)flaky(x)\n@except e:\n    x = 1\n(e)identity(t)\n",
    "(a)f(b) (c)g(d)\n",
    "(a)f(b) x = 1\n",
    "(a)f(b)\n  (c)g(d)\n",
    "ns:\n    (a)f(b) )\n",
    "skip:\n    (x)print(\n",
    "b:\n    x = [1, # c\n",
    "x = .5e-:3\n",
    "@try:\n    x = 1\n    x = 2\n\n",
    'x = """a"\\"""\n',
    "s = 'x'\n(s)inc(y)\n(True)small(c)\n(c)branch(`a`, `b`)\na:\n    q = 1\nb:\n    q = 2\n",
    # Line endings: CRLF and a lone CR are line breaks everywhere.
    "x = 1\ry = 2\r",
    "x = 1\r\ny = 2\r\n",
    "x = 1 # c\ry = 2\n",
    "# c\r\r\nx = 1\n",
    "x = 1\r\n\r",
    "x = '''a\rb'''\n",
    "x = 'a\rb'\n",
    "x = '''a\r\r\nb'''\n",
    "ns:\r    x = 1\r# c\r    y = 2\r",
    "ns:\r\n    x = 1\r  # c\r\n    y = 2\r\n",
    "(a,\r b)foo(c)\r",
    # Dedents to a level no enclosing block has.
    "ns:\r    x = 1\r  y = 2\r",
    "ns:\n    x = 1\n  y = 2",
    "ns:\n\t\tx = 1\n\ty = 2\n",
    "ns:\n        x = 1\n\t  y = 2\n",
    "ns:\n\tx = 1\n  \ty = 2\n",
    "ns:\n    x = 1\n \t y = 2\n",
    "a:\n    b:\n        x = 1\n      y = 2\n",
    "a:\n    b:\n        x = 1\n\t  y = 2\n",
    "ns:\n    x = 1\n\n   # c\n  y = 2\n",
]


def outcome(fn, *args, **kwargs):
    """("ok", value) or ("error",) for any exception."""
    try:
        return ("ok", fn(*args, **kwargs))
    except Exception:
        return ("error",)


def failure(fn, *args, **kwargs):
    """("ok", value) or ("error", exception class, message)."""
    try:
        return ("ok", fn(*args, **kwargs))
    except Exception as exc:
        return ("error", type(exc).__name__, str(exc))


WHERE = re.compile(r"\(line (\d+), column (\w+)\)$")


def parsed(fn, src: str):
    """("ok", text), or ("error", where): the error's (line, column) when it has one.

    Grammar errors are compared by position only (the reference's message also
    quotes the source). An exception that is not a KIR error (lark's DedentError,
    or its indenter's IndexError on a comment before a lone CR) is the
    reference failing on bad input: ("error", ("raises", class)).
    """
    try:
        return ("ok", fn(src))
    except (KirError, _rs.KirError) as exc:
        where = WHERE.search(str(exc))
        return ("error", where.groups() if where else str(exc))
    except Exception as exc:
        return ("error", ("raises", type(exc).__name__))


class Report:
    def __init__(self) -> None:
        self.compared = 0
        self.failures: list[str] = []
        self.seen = Counter()

    def same(self, what: str, src: str, py, rust) -> bool:
        self.compared += 1
        if py == rust:
            return True
        self.failures.append(
            f"--- {what}\nsource:\n{src}\npython: {str(py)[:1500]}\nrust:   {str(rust)[:1500]}"
        )
        return False


# ---------------------------------------------------------------- the Python side


def py_format(src: str) -> str:
    return write(parse(src))


def py_diagnostics(src: str, libs: list, base=None, sig_path=None) -> list[dict]:
    program_ = parse(src)
    try:
        env = build_env(program_, libs, base, sig_path)
    except KirSignatureError as exc:
        return [{"code": "E002", "message": str(exc), "line": None, "severity": "error"}]
    return [
        {"code": d.code, "message": d.message, "line": d.line, "severity": d.severity}
        for d in check(program_, env)
    ]


def py_lower(src: str, libs: list, passes=None, base=None, sig_path=None) -> str:
    return write(compile_program(parse(src), libs, base, sig_path, passes).lowered)


def py_hashes(src: str, libs: list, base=None, sig_path=None) -> dict:
    c = compile_program(parse(src), libs, base, sig_path)
    return {"semantic": c.semantic_hash, "full": c.full_hash}


def py_graph(src: str, libs: list, data="wires", base=None, sig_path=None) -> str:
    p = parse(src)
    graph = to_graph(p, build_env(p, libs, base, sig_path), data)
    return json.dumps(graph, indent=2, ensure_ascii=False) + "\n"


def py_text(graph: str, with_meta: bool) -> str:
    return write(from_graph(json.loads(graph), with_meta))


# ---------------------------------------------------------------- the Rust side


def rs_check(src: str, sigs: list[str], **where) -> list[dict]:
    return json.loads(_rs.check(src, sigs, **where))


def rs_hashes(src: str, sigs: list[str], **where) -> dict:
    return json.loads(_rs.hashes(src, sigs, **where))


# ---------------------------------------------------------------- comparisons


def compare(name: str, src: str, sig_text: str, lib, report: Report) -> None:
    sigs, libs = [sig_text], [lib]
    py = parsed(py_format, src)
    report.seen["parsed" if py[0] == "ok" else "rejected by the parser"] += 1
    rust = parsed(_rs.format, src)
    if py[0] == "error" and py[1][0] == "raises":
        report.seen[f"reference raises {py[1][1]}"] += 1
        report.same(f"{name}: format", src, "error", rust[0])
        return
    if not report.same(f"{name}: format", src, py, rust) or py[0] == "error":
        return
    py_diags = outcome(py_diagnostics, src, libs)
    report.same(f"{name}: check", src, py_diags, outcome(rs_check, src, sigs))
    clean = py_diags[0] == "ok" and not any(d["severity"] == "error" for d in py_diags[1])
    report.seen["checked clean" if clean else "checker errors"] += 1
    if py_diags[0] == "ok":
        report.seen.update(d["code"] for d in py_diags[1])
    if clean:
        names = list(PASSES)
        for k in range(1, len(names) + 1):
            prefix = names[:k]
            report.same(
                f"{name}: passes {prefix}",
                src,
                outcome(py_lower, src, libs, prefix),
                outcome(_rs.lower, src, sigs, prefix),
            )
        report.same(
            f"{name}: hashes", src, outcome(py_hashes, src, libs), outcome(rs_hashes, src, sigs)
        )
    for data in DATA_STYLES:
        py_g = outcome(py_graph, src, libs, data)
        report.seen[f"graph ({data})" if py_g[0] == "ok" else f"no graph ({data})"] += 1
        rs_g = outcome(_rs.to_graph, src, sigs, data)
        if not report.same(f"{name}: to_graph {data}", src, py_g, rs_g) or py_g[0] != "ok":
            continue
        for with_meta in (True, False):
            report.same(
                f"{name}: from_graph {data} with_meta={with_meta}",
                src,
                outcome(py_text, py_g[1], with_meta),
                outcome(_rs.from_graph, py_g[1], with_meta),
            )


def tiny_graph(value: str, meta: str, hints: str) -> str:
    """A one-node graph text with the given JSON for its value, meta and hints."""
    node = (
        f'{{"id": "v", "kind": "assign", "inputs": [{{"port": "value", "value": {value}}}], '
        f'"outputs": [{{"port": "value", "var": "x"}}], "ctrl_in": [], "ctrl_out": [], '
        f'"meta": {meta}, "hints": {hints}}}'
    )
    return graph_text([node], [])


def graph_text(nodes: list[str], edges: list[tuple[str, str, str, str]]) -> str:
    """A one-graph `.kirgraph` text: node JSON texts and (from, port, to, port) data edges."""
    wires = [
        f'{{"kind": "data", "from": {{"node": "{a}", "port": "{p}"}}, '
        f'"to": {{"node": "{b}", "port": "{q}"}}}}'
        for a, p, b, q in edges
    ]
    graph = f'{{"name": "main", "nodes": [{", ".join(nodes)}], "edges": [{", ".join(wires)}]}}'
    return f'{{"kirgraph": 2, "uses": [], "graphs": [{graph}]}}'


def value_node(nid: str, value: str) -> str:
    return f'{{"id": "{nid}", "kind": "value", "props": {{"value": {value}}}, "outputs": [{{"port": "value"}}]}}'


def var_node(nid: str, kind: str, name: str) -> str:
    port = "outputs" if kind == "get" else "inputs"
    return f'{{"id": "{nid}", "kind": "{kind}", "props": {{"name": "{name}"}}, "{port}": [{{"port": "value"}}]}}'


def ports_text(names: list[str]) -> str:
    return ", ".join(f'{{"port": "{n}"}}' for n in names)


def node_text(nid: str, kind: str, ins: list[str], outs: list[str], extra: str = "") -> str:
    return (
        f'{{"id": "{nid}", "kind": "{kind}"{extra}, "inputs": [{ports_text(ins)}], '
        f'"outputs": [{ports_text(outs)}], "ctrl_in": [], "ctrl_out": []}}'
    )


def editor_graphs() -> list[str]:
    """Graphs drawn the way an editor draws them: value, get and set variable nodes."""
    add = node_text("add", "call", ["a", "b"], ["sum"], ', "name": "add"')
    eq = node_text("eq", "assign", ["value"], ["value"])
    out = []
    for value in GRAPH_VALUES:
        out.append(
            graph_text(
                [value_node("one", value), add, var_node("s", "set", "total")],
                [("one", "value", "add", "a"), ("add", "sum", "s", "value")],
            )
        )
        out.append(graph_text([value_node("one", value), eq], [("one", "value", "eq", "value")]))
    out += [
        # One output wired into two `set` nodes: same name, then two names.
        graph_text(
            [add, var_node("s1", "set", "t"), var_node("s2", "set", "t")],
            [("add", "sum", "s1", "value"), ("add", "sum", "s2", "value")],
        ),
        graph_text(
            [add, var_node("s1", "set", "t"), var_node("s2", "set", "u")],
            [("add", "sum", "s1", "value"), ("add", "sum", "s2", "value")],
        ),
        # A `get` read into an assign, an assign whose input has no wire and no value.
        graph_text(
            [var_node("g", "get", "t"), eq, var_node("s", "set", "y")],
            [("g", "value", "eq", "value"), ("eq", "value", "s", "value")],
        ),
        graph_text([eq], []),
        # A `set` with nothing wired in, a `value` node read by nothing.
        graph_text([var_node("s", "set", "y"), value_node("v", "1")], []),
        # value -> add -> set out; get out -> assign -> set y (tests/test_graph.py).
        graph_text(
            [
                value_node("one", "1"),
                '{"id": "add", "kind": "call", "name": "add", "inputs": [{"port": "a"}, '
                '{"port": "b", "value": 2}], "outputs": [{"port": "sum"}], '
                '"ctrl_in": [], "ctrl_out": []}',
                var_node("out", "set", "out"),
                var_node("x", "get", "out"),
                eq,
                var_node("y", "set", "y"),
            ],
            [
                ("one", "value", "add", "a"),
                ("add", "sum", "out", "value"),
                ("x", "value", "eq", "value"),
                ("eq", "value", "y", "value"),
            ],
        ),
    ]
    return out


GRAPH_VALUES = ["1", "1.5", "Infinity", "-Infinity", "NaN", "[1, Infinity]", '{"tuple": [NaN]}']
GRAPH_VALUES += [
    '{"pairs": [[Infinity, 1]]}',
    '{"dict": {"a": NaN}}',
    '{"tuple": [1]}',
    '{"tuple": []}',
]
GRAPH_META = [
    "{}",
    '{"pos": [1, 2]}',
    '{"pos": [1]}',
    '{"pos": []}',
    '{"pos": [NaN]}',
    '{"m": {"a": Infinity}}',
]
GRAPH_HINTS = ["{}", '{"h": 1}', '{"h": Infinity}', '{"h": [1, NaN]}', '{"h": {"k": -Infinity}}']


def compare_graphs(report: Report) -> None:
    """Graph literals, meta and hints with non-finite numbers and short tuples."""
    for value in GRAPH_VALUES:
        for meta in GRAPH_META:
            for hints in GRAPH_HINTS:
                g = tiny_graph(value, meta, hints)
                for with_meta in (True, False):
                    report.same(
                        f"graph literal with_meta={with_meta}",
                        g,
                        outcome(py_text, g, with_meta),
                        outcome(_rs.from_graph, g, with_meta),
                    )
    for g in editor_graphs():
        for with_meta in (True, False):
            report.same(
                f"editor graph with_meta={with_meta}",
                g,
                failure(py_text, g, with_meta),
                failure(_rs.from_graph, g, with_meta),
            )
    for data in ("wire", "Variables", ""):
        report.same(
            f"to_graph data={data!r}",
            "x = 1\n",
            failure(py_graph, "x = 1\n", [], data),
            failure(_rs.to_graph, "x = 1\n", [], data),
        )


def compare_resolution(report: Report) -> None:
    """`@use` through the signature path and through `.kirsig.json` paths, files on disk."""
    gen = json.dumps(library_to_json(LIB), indent=2)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        files = {
            "sigs/gen.kirsig.json": gen,
            "proj/local.kirsig.json": gen,
            "proj/sub/other.kirsig.json": gen.replace('"library": "gen"', '"library": "other"'),
            "sigs/bad.kirsig.json": "{not json",
            "sigs/trailing.kirsig.json": '{"kirsig": 1, "library": "t", "nodes": [],}',
            "sigs/nokey.kirsig.json": '{"kirsig": 1, "library": "nokey"}',
            "sigs/fmt2.kirsig.json": '{"kirsig": 2, "library": "fmt2", "nodes": []}',
            "sigs/dup.kirsig.json": '{"kirsig": 1, "library": "dup", "nodes": '
            '[{"name": "a"}, {"name": "a"}]}',
            "sigs/badtype.kirsig.json": '{"kirsig": 1, "library": "bt", "nodes": '
            '[{"name": "a", "inputs": [{"name": "x", "type": "int]"}]}]}',
        }
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        (root / "empty").mkdir()
        sigs, proj = str(root / "sigs"), str(root / "proj")
        odd_path = [sigs, (root / "empty").as_posix() + "/", tmp + "/./sigs//"]
        absolute = (root / "proj" / "local.kirsig.json").as_posix()
        cases = [
            ('@use "gen"\n(1)inc(x)\n(x)inc(y)\n', None, [sigs]),
            ('@use "gen" as g\n(1)g.inc(x)\n(x, 2)g.mix(y)\n', None, [sigs]),
            ('@use "local.kirsig.json" as l\n(1)l.inc(x)\n', proj, []),
            ('@use "sub/other.kirsig.json"\n(1)inc(x)\n', proj, []),
            (f'@use "{absolute}"\n(1)inc(x)\n', None, []),
            ('@use "nolib"\n(1)inc(x)\n', None, odd_path),
            ('@use "nolib"\n', None, []),
            ('@use "missing.kirsig.json"\n', proj, []),
            ('@use "local.kirsig.json"\n', None, []),
            ('@use "bad"\n', None, [sigs]),
            ('@use "trailing"\n', None, [sigs]),
            ('@use "nokey"\n', None, [sigs]),
            ('@use "fmt2"\n', None, [sigs]),
            ('@use "dup"\n', None, [sigs]),
            ('@use "badtype"\n', None, [sigs]),
            ('@use "gen"\n(1)nothere(x)\n', None, [sigs]),
        ]
        for src, base, path in cases:
            py_where = {
                "base": Path(base) if base is not None else None,
                "sig_path": [Path(p) for p in path],
            }
            rs_where = {"base": base, "sig_path": path}
            what = f"resolution base={base} sig_path={path}"
            py_check = failure(py_diagnostics, src, [], **py_where)
            report.same(f"check {what}", src, py_check, failure(rs_check, src, [], **rs_where))
            e002 = py_check[0] == "ok" and any(d["code"] == "E002" for d in py_check[1])
            report.seen["resolution E002" if e002 else "resolved"] += 1
            report.same(
                f"lower {what}",
                src,
                failure(py_lower, src, [], **py_where),
                failure(_rs.lower, src, [], **rs_where),
            )
            report.same(
                f"hashes {what}",
                src,
                failure(py_hashes, src, [], **py_where),
                failure(rs_hashes, src, [], **rs_where),
            )
            for data in DATA_STYLES:
                report.same(
                    f"to_graph {data} {what}",
                    src,
                    failure(py_graph, src, [], data, **py_where),
                    failure(_rs.to_graph, src, [], data, **rs_where),
                )


IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Single characters a mutation inserts: every punctuation of the grammar plus
# characters no terminal matches.
CHARS = list("()[]{},:=|?.`@#'\"_+-0x eE\t$!>\\é") + ["=>", "\n", "\r", "True", "None", "\\N{"]


def mutate(src: str, r: random.Random) -> str:
    lines = src.split("\n")
    i = r.randrange(len(lines))
    kind = r.choice(
        ["delete", "duplicate", "swap", "rename", "indent", "comment", "snippet", "char", "cut"]
        + ["eol"]
    )
    if kind == "eol":
        return r.choice(["\r", "\r\n"]).join(lines)
    if kind == "char":
        k = r.randrange(len(lines[i]) + 1)
        lines[i] = lines[i][:k] + r.choice(CHARS) + lines[i][k:]
    elif kind == "cut" and lines[i]:
        k = r.randrange(len(lines[i]))
        lines[i] = lines[i][:k] + lines[i][k + 1 :]
    elif kind == "delete":
        del lines[i]
    elif kind == "duplicate":
        lines.insert(i, lines[i])
    elif kind == "swap":
        j = r.randrange(len(lines))
        lines[i], lines[j] = lines[j], lines[i]
    elif kind == "rename":
        words = IDENT.findall(src) or ["x"]
        old, new = r.choice(words), r.choice(words + ["_t", "Truex", "a__b", "kir.next_index"])
        lines[i] = re.sub(rf"\b{re.escape(old)}\b", new, lines[i])
    elif kind == "indent":
        lines[i] = r.choice(["    ", "\t", "  "]) + lines[i] if r.random() < 0.6 else lines[i][4:]
    elif kind == "comment":
        lines.insert(i, r.choice(["", "    ", "        "]) + "# note")
    else:
        lines.insert(i, r.choice(["", "    "]) + r.choice(SNIPPETS).rstrip("\n").split("\n")[0])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=300)
    ap.add_argument("--mutations", type=int, default=4)
    ap.add_argument("--show", type=int, default=20, help="differences to print")
    ap.add_argument("--rng", type=int, default=1234, help="seed of the mutations")
    args = ap.parse_args()
    report = Report()
    r = random.Random(args.rng)
    report.same(
        "std signatures",
        "",
        json.dumps(library_to_json(STD), indent=2, ensure_ascii=False) + "\n",
        _rs.std_signatures(),
    )
    compare_graphs(report)
    compare_resolution(report)
    sources: list[tuple[str, str, str]] = []
    for d in sorted(CASES.iterdir()):
        sig = (d / "sig.kirsig.json").read_text(encoding="utf-8")
        sources.append((d.name, (d / "input.kir").read_text(encoding="utf-8"), sig))
    gen_sig = json.dumps(library_to_json(LIB))
    for seed in range(args.seeds):
        sources.append((f"progen {seed}", program(seed), gen_sig))
        sources.append((f"progen entry {seed}", entry_program(seed).text, gen_sig))
    v1_sig = (CASES / "v2__features" / "sig.kirsig.json").read_text(encoding="utf-8")
    for i, snippet in enumerate(SNIPPETS):
        sources.append((f"snippet {i}", snippet, gen_sig))
        sources.append((f"snippet {i} (v1 library)", snippet, v1_sig))
    for name, src, sig in sources:
        lib = library_from_json(json.loads(sig))
        compare(name, src, sig, lib, report)
        for m in range(args.mutations):
            compare(f"{name} mutation {m}", mutate(src, r), sig, lib, report)
    for f in report.failures[: args.show]:
        print(f)
    print("coverage:", ", ".join(f"{k} {v}" for k, v in sorted(report.seen.items())))
    print(
        f"{len(sources)} sources, {report.compared} comparisons, "
        f"{len(report.failures)} differences"
    )
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
