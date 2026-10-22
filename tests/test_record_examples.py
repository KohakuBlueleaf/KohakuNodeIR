"""The schema-only record example runs without importing any host implementation."""

import json
import subprocess
import sys
from pathlib import Path

from kohakunode import Interpreter, compile_file
from kohakunode.sig import load_library

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "records"


def test_signature_only_records_example_runner():
    result = subprocess.run(
        [sys.executable, str(EXAMPLE / "run.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "signature-only: generated operations, no imported host implementation" in result.stdout
    assert "reference: every lowering pass prefix agrees" in result.stdout
    assert "graph: wires and variables roundtrips agree" in result.stdout
    assert "alias safety: input, projection and replacement lists are independent" in result.stdout
    assert "codec: nested Request/Point roundtrip and digest match" in result.stdout


def test_record_example_schema_and_reference_results():
    schema_path = EXAMPLE / "geometry.kirsig.json"
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    assert data["kirsig"] == 2 and data["nodes"] == []
    library = load_library(schema_path)
    assert set(library.records) == {"Request", "Point"}
    assert library.records["Request"].field("point").type.name == "geometry.Point"
    compiled = compile_file(EXAMPLE / "main.kir")
    interpreter = Interpreter(compiled.lowered, compiled.env)
    interpreter.run()
    values = interpreter.source_values()
    assert values["original_x"] == 1.0 and values["updated_x"] == 3.0
    assert values["original_tags"] == ["input"]
    assert values["reviewed_tags"] == ["input", "reviewed"]
    assert values["nullable_label"] is values["nullable_fallback"] is None
    assert values["original"]["point"]["x"] == 1.0
    assert values["updated"]["point"]["x"] == 3.0
