"""Smoke tests of the HTTP API against the golden corpus and the shipped samples."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kir_editor.app import create_app
from kir_editor.config import Settings

APP_DIR = Path(__file__).resolve().parents[2]
REPO = APP_DIR.parents[1]
CASES = REPO / "tests" / "corpus" / "golden" / "cases"
SAMPLES = APP_DIR / "frontend" / "src" / "samples"
SIG_DIR = APP_DIR / "backend" / "signatures"

ROUND_TRIP_CASES = ["v1__examples__kir_basics__control_flow", "v2__features", "v2__each"]


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(Settings(sig_dirs=[SIG_DIR])))


def _case(name: str) -> tuple[str, dict, Path]:
    d = CASES / name
    sig = json.loads((d / "sig.kirsig.json").read_text(encoding="utf-8"))
    return (d / "input.kir").read_text(encoding="utf-8"), sig, d


@pytest.mark.parametrize("name", ROUND_TRIP_CASES)
def test_text_graph_text_round_trip(client, name):
    text, sig, d = _case(name)
    scope = {"signatures": [sig], "use_demo": False}
    g = client.post("/api/graph", json={"text": text, **scope}).json()
    # The graph the backend sends is the golden graph, byte for byte.
    golden = (d / "graph.kirgraph").read_text(encoding="utf-8")
    assert json.dumps(g["graph"], indent=2, ensure_ascii=False) + "\n" == golden
    assert not [x for x in g["diagnostics"] if x["severity"] == "error"]

    t1 = client.post("/api/text", json={"graph": g["graph"], "with_meta": True, **scope}).json()
    assert t1["text"] and not [x for x in t1["diagnostics"] if x["severity"] == "error"]
    g2 = client.post("/api/graph", json={"text": t1["text"], **scope}).json()
    t2 = client.post("/api/text", json={"graph": g2["graph"], "with_meta": True, **scope}).json()
    assert t2["text"] == t1["text"]
    assert (
        g2["graph"] == client.post("/api/graph", json={"text": t2["text"], **scope}).json()["graph"]
    )

    # The source lowers to the golden program; the round-tripped text means the same.
    hashes = json.loads((d / "hashes.json").read_text(encoding="utf-8"))
    lowered = client.post("/api/lower", json={"text": text, **scope}).json()
    assert lowered["lowered"] == (d / "lowered.kir").read_text(encoding="utf-8")
    assert lowered["semantic_hash"] == hashes["semantic"]
    again = client.post("/api/lower", json={"text": t1["text"], **scope}).json()
    assert again["semantic_hash"] == hashes["semantic"]


def test_text_without_meta_is_canonical(client):
    text, sig, d = _case("v1__examples__kir_basics__control_flow")
    scope = {"signatures": [sig], "use_demo": False}
    g = client.post("/api/graph", json={"text": text, **scope}).json()["graph"]
    t = client.post("/api/text", json={"graph": g, "with_meta": False, **scope}).json()["text"]
    assert t == (d / "canonical.kir").read_text(encoding="utf-8")


def test_passes_are_selectable(client):
    text = (SAMPLES / "clamp.kir").read_text(encoding="utf-8")
    passes = {p["name"]: p for p in client.get("/api/passes").json()["passes"]}
    assert passes["inline"]["needs"] == ["order_dataflow"]
    written = client.post("/api/lower", json={"text": text, "passes": []}).json()["lowered"]
    inlined = client.post(
        "/api/lower", json={"text": text, "passes": ["order_dataflow", "inline"]}
    ).json()
    assert "@def" in written and "@def" not in inlined["lowered"]
    for bad_passes, says in ((["nope"], "unknown pass"), (["inline"], "needs")):
        bad = client.post("/api/lower", json={"text": text, "passes": bad_passes}).json()
        assert bad["lowered"] is None and says in bad["diagnostics"][0]["message"]
    as_written = client.post("/api/run", json={"text": text, "passes": []}).json()
    assert as_written["ok"] and as_written["stdout"] == "20.0\n47.5\n"


def test_editor_built_graph_becomes_text(client):
    """Nodes as the editor makes them: an assign chain, a free assign named by a set, a get, a keyword input."""
    graph = {
        "kirgraph": 2,
        "uses": [{"library": "vision", "alias": None}],
        "graphs": [
            {
                "name": "main",
                "nodes": [
                    {
                        "id": "assign_1",
                        "kind": "assign",
                        "inputs": [{"port": "value", "value": "a.png"}],
                        "outputs": [{"port": "value", "var": "path"}],
                        "ctrl_in": ["in"],
                        "ctrl_out": ["out"],
                    },
                    {
                        "id": "load_image_2",
                        "kind": "call",
                        "name": "load_image",
                        "inputs": [{"port": "path", "type": "str"}],
                        "outputs": [{"port": "image", "var": "image", "type": "Image"}],
                        "ctrl_in": ["in"],
                        "ctrl_out": ["out"],
                    },
                    {
                        "id": "detect_3",
                        "kind": "call",
                        "name": "detect",
                        "inputs": [
                            {"port": "image", "type": "Image"},
                            {"port": "threshold", "type": "float", "keyword": True, "value": 0.8},
                        ],
                        "outputs": [{"port": "boxes", "var": "boxes", "type": "list[Box]"}],
                        "ctrl_in": ["in"],
                        "ctrl_out": ["out"],
                    },
                    {
                        "id": "assign_4",
                        "kind": "assign",
                        "inputs": [{"port": "value", "value": 2}],
                        "outputs": [{"port": "value"}],
                        "ctrl_in": [],
                        "ctrl_out": [],
                    },
                    {
                        "id": "set_5",
                        "kind": "set",
                        "props": {"name": "scale"},
                        "inputs": [{"port": "value"}],
                    },
                    {
                        "id": "get_6",
                        "kind": "get",
                        "props": {"name": "path"},
                        "outputs": [{"port": "value"}],
                    },
                ],
                "edges": [
                    {
                        "kind": "ctrl",
                        "from": {"node": "assign_1", "port": "out"},
                        "to": {"node": "load_image_2", "port": "in"},
                    },
                    {
                        "kind": "data",
                        "from": {"node": "assign_4", "port": "value"},
                        "to": {"node": "set_5", "port": "value"},
                    },
                    {
                        "kind": "ctrl",
                        "from": {"node": "load_image_2", "port": "out"},
                        "to": {"node": "detect_3", "port": "in"},
                    },
                    {
                        "kind": "data",
                        "from": {"node": "get_6", "port": "value"},
                        "to": {"node": "load_image_2", "port": "path"},
                    },
                    {
                        "kind": "data",
                        "from": {"node": "load_image_2", "port": "image"},
                        "to": {"node": "detect_3", "port": "image"},
                    },
                ],
            }
        ],
    }
    out = client.post("/api/text", json={"graph": graph, "with_meta": False}).json()
    assert out["diagnostics"] == []
    assert out["text"] == (
        '@use "vision"\n\n'
        "@dataflow:\n"
        "    scale = 2\n"
        'path = "a.png"\n'
        "(path)load_image(image)\n"
        "(image, threshold=0.8)detect(boxes)\n"
    )


CASE_NAMES = sorted(p.name for p in CASES.iterdir())


@pytest.mark.parametrize("name", CASE_NAMES)
def test_ast_json_writes_the_golden_canonical_text(client, name):
    """AST -> JSON -> AST loses nothing: written back it is the golden canonical text, byte for byte."""
    text, sig, d = _case(name)
    scope = {"signatures": [sig], "use_demo": False}
    ast = client.post("/api/graph", json={"text": text, **scope}).json()["ast"]
    out = client.post("/api/ast/text", json={"ast": ast, **scope}).json()
    assert out["text"] == (d / "canonical.kir").read_text(encoding="utf-8")


def test_variables_style_is_the_golden_variables_graph(client):
    text, sig, d = _case("v2__features")
    scope = {"signatures": [sig], "use_demo": False}
    g = client.post("/api/graph", json={"text": text, "data": "variables", **scope}).json()
    golden = (d / "graph.variables.kirgraph").read_text(encoding="utf-8")
    assert json.dumps(g["graph"], indent=2, ensure_ascii=False) + "\n" == golden
    bad = client.post("/api/graph", json={"text": text, "data": "nope", **scope}).json()
    assert bad["graph"] is None and "unknown data style" in bad["diagnostics"][0]["message"]


def _node_ids(stmts):
    for s in stmts:
        if "node_id" in s.get("meta", {}):
            yield s["meta"]["node_id"]
        for k in ("body", "handler"):
            yield from _node_ids(s.get(k, []))


@pytest.mark.parametrize("data", ["wires", "variables"])
def test_structure_tags_statements_with_their_nodes(client, data):
    """Every structure statement names a node of its graph, and each call/assign node appears once."""
    text, sig, _ = _case("v2__features")
    scope = {"signatures": [sig], "use_demo": False}
    out = client.post("/api/graph", json={"text": text, "data": data, **scope}).json()
    for g in out["graph"]["graphs"]:
        ids = list(_node_ids(out["structure"][g["name"]]))
        nodes = {n["id"]: n for n in g["nodes"]}
        assert set(ids) <= set(nodes), (g["name"], set(ids) - set(nodes))
        statements = [n["id"] for n in g["nodes"] if n["kind"] in ("call", "assign")]
        assert sorted(i for i in ids if nodes[i]["kind"] in ("call", "assign")) == sorted(
            statements
        )
    main = out["structure"]["main"]
    types = [s["type"] for s in main]
    assert types[types.index("switch") + 1 : types.index("switch") + 4] == ["namespace"] * 3


def test_ast_text_reports_bad_json(client):
    out = client.post("/api/ast/text", json={"ast": {"body": [{"type": "nope"}]}}).json()
    assert out["text"] is None and "unknown statement type" in out["diagnostics"][0]["message"]


@pytest.mark.parametrize(
    "text, code, line",
    [
        ("(x)print_val()\n", "E020", 1),
        ("a = 1\n(a)no_such_node(b)\n", "E010", 2),
        ("a = = 1\n", "E001", 1),
        ('@use "nowhere"\na = 1\n', "E002", None),
        ("(True)branch(`t`, `f`)\nt:\n    a = 1\n", "E030", 1),
    ],
)
def test_check_reports_diagnostics(client, text, code, line):
    out = client.post("/api/check", json={"text": text}).json()["diagnostics"]
    hits = [d for d in out if d["code"] == code]
    assert hits, out
    assert hits[0]["line"] == line
    assert hits[0]["severity"] == "error"


def test_check_warning_is_not_an_error(client):
    out = client.post("/api/check", json={"text": "a = 1\nunused:\n    b = 2\n"}).json()
    assert [(d["code"], d["severity"]) for d in out["diagnostics"]] == [("W001", "warning")]


def test_demo_overlap_is_ambiguous(client):
    """A given library that shares a node with demo makes the unaliased call ambiguous."""
    text, sig, _ = _case("v1__examples__kir_basics__control_flow")
    out = client.post("/api/check", json={"text": text, "signatures": [sig]}).json()
    assert "E011" in {d["code"] for d in out["diagnostics"]}


@pytest.mark.parametrize(
    "sample, stdout, values",
    [
        ("factorial.kir", "5! = 120\n", {"result": 120, "counter": 6}),
        ("clamp.kir", "20.0\n47.5\n", {"avg": 20.0, "avg2": 47.5}),
        ("each.kir", "", {"summary": "2 of 3 boxes hold an entity"}),
        (
            "tour.kir",
            "error in g.crop: ValueError: box -1 is outside the image\n",
            {"out": [None, "entity(img[2])", 30, 2]},
        ),
    ],
)
def test_samples_run(client, sample, stdout, values):
    text = (SAMPLES / sample).read_text(encoding="utf-8")
    out = client.post("/api/run", json={"text": text}).json()
    assert out["ok"], out
    assert out["stdout"] == stdout
    for k, v in values.items():
        assert out["values"][k] == v


def test_runtime_failure_is_a_diagnostic(client):
    out = client.post("/api/run", json={"text": 'c = 0\n("img", -3)crop(c)\n'}).json()
    assert not out["ok"]
    assert out["diagnostics"][-1]["code"] == "runtime"
    assert out["diagnostics"][-1]["line"] == 2


def test_signatures_lists_std_demo_and_directory(client):
    libs = client.get("/api/signatures").json()["libraries"]
    names = [lib["library"] for lib in libs]
    assert names == ["kir.std", "demo", "vision"]
    vision = libs[2]
    assert vision["source"] == "vision.kirsig.json" and not vision["runnable"]
    detect = next(n for n in vision["nodes"] if n["name"] == "detect")
    assert detect["outputs"] == [{"name": "boxes", "type": "list[Box]"}]


def test_signature_path_library_resolves(client):
    text = '@use "vision" as v\n("a.png")v.load_image(img)\n(img)v.detect(boxes)\n'
    g = client.post("/api/graph", json={"text": text}).json()
    assert g["diagnostics"] == []
    detect = g["graph"]["graphs"][0]["nodes"][1]
    assert detect["outputs"] == [{"port": "boxes", "var": "boxes", "type": "list[Box]"}]
