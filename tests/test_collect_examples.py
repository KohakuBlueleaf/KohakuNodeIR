"""The generic collection example runs its reference/lowering/graph checks."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_collect_example():
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples/collect/run.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"result": [3, null, 7]' in result.stdout
    assert '"rows": [[], [0, 1], [0, 1, 4]]' in result.stdout
    assert "reference: private append and all lowering pass prefixes agree" in result.stdout
    assert "graph: wires and variables roundtrips agree" in result.stdout
