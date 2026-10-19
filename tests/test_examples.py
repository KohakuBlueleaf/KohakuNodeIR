import contextlib
import io
import runpy
from pathlib import Path

RUNNER = Path(__file__).parent.parent / "examples" / "run_examples.py"


def test_every_example_checks_lowers_and_runs():
    module = runpy.run_path(str(RUNNER))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = module["main"]()
    assert status == 0, out.getvalue()
    assert "image -> cat" in out.getvalue()
