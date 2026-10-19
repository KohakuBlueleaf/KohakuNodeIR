import json
from pathlib import Path

from kohakunode import parse, write
from kohakunode.cli.main import main
from kohakunode.comfyui import from_comfyui, to_api

EXAMPLES = Path(__file__).parent.parent / "examples" / "comfyui"


def test_comfyui_api_round_trip():
    prompt = json.loads((EXAMPLES / "workflow_api.json").read_text(encoding="utf-8"))
    program = from_comfyui(prompt)
    text = write(program)
    assert to_api(parse(text)) == {str(k): v for k, v in prompt.items()}


def test_comfyui_ui_reads():
    workflow = json.loads((EXAMPLES / "workflow_ui.json").read_text(encoding="utf-8"))
    program = from_comfyui(workflow)
    calls = program.body[0].body
    assert len(calls) == len(workflow["nodes"])
    assert parse(write(program)).body == program.body


def test_cli_lower_and_graph(tmp_path, capsys):
    src = tmp_path / "p.kir"
    src.write_text("x = [1, 2]\n(x)len(n)\n(n, 1)add(m)\n", encoding="utf-8")
    assert main(["check", str(src)]) == 0
    capsys.readouterr()
    assert main(["lower", str(src), "--hash"]) == 0
    assert capsys.readouterr().out.startswith("semantic ")
    graph = tmp_path / "p.kirgraph"
    assert main(["graph", str(src), "-o", str(graph)]) == 0
    assert main(["text", str(graph), "--no-meta"]) == 0
    assert capsys.readouterr().out == "x = [1, 2]\n(x)len(n)\n(n, 1)add(m)\n"
    assert main(["run", str(src)]) == 0
    assert json.loads(capsys.readouterr().out) == {"m": 3, "n": 2, "x": [1, 2]}
    bad = tmp_path / "bad.kir"
    bad.write_text("(y)len(n)\n", encoding="utf-8")
    assert main(["check", str(bad)]) == 1


def test_cli_sig_export_then_use(tmp_path):
    sigs = tmp_path / "new" / "sigs"
    assert main(["sig", "export", "examples.tour.nodes", "-o", str(sigs)]) == 0
    assert json.loads((sigs / "tour.kirsig.json").read_text(encoding="utf-8"))["library"] == "tour"
    src = tmp_path / "p.kir"
    src.write_text('@use "tour"\n("photo", 1)crop(c)\n', encoding="utf-8")
    assert main(["check", str(src)]) == 1
    assert main(["check", str(src), "--sig-path", str(sigs)]) == 0
