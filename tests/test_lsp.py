import json
import subprocess
import sys

import pytest

from kohakunode.lsp.analysis import (
    CORES,
    analyze,
    completions,
    default_core,
    definition,
    format_text,
    hover,
)

SRC = """@def (a: int)twice(out: int):
    (a, a)add(out)

(3)twice(x)
(x)branch(`yes`, `no`)
yes:
    (y)neg(z)
no:
"""


@pytest.mark.parametrize("core", CORES)
def test_analysis_queries(core):
    a = analyze(SRC, core=core)
    codes = {(p.code, p.line) for p in a.problems}
    assert ("E041", 4) in codes and ("E020", 6) in codes
    assert "twice" in hover(a, SRC, 3, 4)
    assert "a: _" in hover(a, SRC, 1, 12) and "kir.std" in hover(a, SRC, 1, 12)
    assert definition(a, SRC, 4, 11) == 5
    assert definition(a, SRC, 3, 5) == 0
    labels = completions(a, "(x)branch(`", 0, 11)
    assert ("yes", "label") in labels
    assert ("twice", "def") in completions(a, SRC, 8, 0)
    bad = analyze("x = 1\n(x)f(\n", core=core).problems
    assert [p.code for p in bad] == ["E001"]
    assert format_text("x=1\n", core) == "x = 1\n"
    assert format_text("(x)f(\n", core) is None


def test_cores_agree(tmp_path):
    sigs = tmp_path / "sigs"
    sigs.mkdir()
    (sigs / "lib.kirsig.json").write_text(
        json.dumps(
            {
                "kirsig": 1,
                "library": "lib",
                "nodes": [
                    {
                        "name": "inc",
                        "inputs": [{"name": "x", "type": "int"}],
                        "outputs": [{"name": "y", "type": "int"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    path = str(tmp_path / "p.kir")
    for text in (
        SRC,
        '@use "lib"\n(1)inc(a)\n("s")inc(b)\n(c)inc(d)\n',
        '@use "missing"\nx = 1\n',
        '@use "lib.kirsig.json"\n(1)inc(a)\n',
        "True = 1\n",
        "x = 1\n    y = 2\n",
        "(x)f(\n",
    ):
        py = analyze(text, path, [str(sigs)], "python").problems
        rs = analyze(text, path, [str(sigs)], "rust").problems
        if py and py[0].code == "E001":
            # Rust's grammar errors leave out lark's context snippet.
            assert [(p.code, p.line, p.start) for p in rs] == [
                (p.code, p.line, p.start) for p in py
            ]
        else:
            assert rs == py, text
    assert default_core() == "rust"


def _frame(msg: dict) -> bytes:
    body = json.dumps(msg).encode()
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def _read(stream) -> dict:
    length = 0
    while True:
        line = stream.readline().decode().strip()
        if not line:
            break
        if line.lower().startswith("content-length"):
            length = int(line.split(":")[1])
    return json.loads(stream.read(length))


def test_server_publishes_diagnostics():
    proc = subprocess.Popen(
        [sys.executable, "-m", "kohakunode.lsp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        uri = "file:///tmp/a.kir"
        for msg in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "kir",
                        "version": 1,
                        "text": "(y)len(n)\n",
                    }
                },
            },
        ):
            proc.stdin.write(_frame(msg))
        proc.stdin.flush()
        diagnostics = None
        for _ in range(10):
            msg = _read(proc.stdout)
            if msg.get("method") == "textDocument/publishDiagnostics":
                diagnostics = msg["params"]["diagnostics"]
                break
        assert diagnostics and diagnostics[0]["code"] == "E020"
    finally:
        proc.kill()
