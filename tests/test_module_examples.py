"""The imported-library example is executable as documented."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_imported_library_reference_example():
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples/modules/run.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reference: linked and lowered results match" in result.stdout
    assert "origins: same definition node, two distinct call-site chains" in result.stdout
    assert '"module": "transforms.kir"' in result.stdout
    assert '"definition": "decorate"' in result.stdout
