import json

import pytest

from kohakunode import (
    Interpreter,
    KirCheckError,
    NodeLibrary,
    build_env,
    check,
    compile_source,
    parse,
    write,
)
from kohakunode.sig import library_from_json, library_to_json, save_library

LIB = NodeLibrary("t")


@LIB.node(outputs=["crop"])
def crop(image: str, box: int) -> str:
    return f"{image}[{box}]"


@LIB.node(outputs=["node"])
def entity(crop: str) -> str:
    if crop.endswith("[13]"):
        raise ValueError("bad box")
    return f"E({crop})"


@LIB.node(outputs=["flag"])
def is_new(box: int) -> bool:
    return box % 2 == 1


def run_lowered(src: str, libs=(LIB,), hook=None):
    c = compile_source(src, list(libs))
    interp = Interpreter(c.lowered, c.env, hook=hook)
    interp.run()
    return interp.source_values(), c


def run_as_written(src: str, libs=(LIB,)):
    p = parse(src)
    interp = Interpreter(p, build_env(p, list(libs)))
    return interp.run()


EACH = """
image = "img"
boxes = [1, 2, 3]
nodes = []
(boxes)each(b, i, `body`)
body:
    (b)is_new(fresh)
    (fresh)branch(`yes`, `no`)
    yes:
        (image, b)crop(c)
        (c)entity(node)
    no:
        node = None
    (nodes, node)append(nodes)
"""

HAND = """
image = "img"
boxes = [1, 2, 3]
nodes = []
i = 0
(boxes)len(n)
()jump(`loop`)
loop:
    (i, n)less(more)
    (more)branch(`body`, `done`)
    body:
        (boxes, i)item_at(b)
        (b)is_new(fresh)
        (fresh)branch(`yes`, `no`)
        yes:
            (image, b)crop(c)
            (c)entity(node)
        no:
            node = None
        (nodes, node)append(nodes)
        (i, 1)add(i)
        ()jump(`loop`)
    done:
"""


def test_each_matches_hand_written_loop():
    a, _ = run_lowered(EACH)
    b, _ = run_lowered(HAND)
    assert a["nodes"] == b["nodes"] == ["E(img[1])", None, "E(img[3])"]
    assert a["b"] == 3 and a["i"] == 2
    assert run_as_written(EACH)["nodes"] == a["nodes"]


def test_lowered_shape():
    _, c = run_lowered(EACH)
    text = write(c.lowered)
    assert "@mode" not in text
    assert "kir.item_at" in text and "@meta" not in text
    assert parse(text).body == c.lowered.body


def test_partial_passes():
    c = compile_source(EACH, [LIB], passes=["order_dataflow", "expand_each"])
    assert "kir.item_at" in write(c.lowered) and "__1" not in write(c.lowered).split("each__")[0]
    with pytest.raises(ValueError, match="needs"):
        compile_source(EACH, [LIB], passes=["version"])


def test_try_binds_error_and_keeps_earlier_writes():
    src = """
image = "img"
@try:
    (image, 12)crop(c)
    (image, 13)crop(c2)
    (c2)entity(node)
    note = "unreachable"
@except err:
    node = None
note2 = "after"
"""
    values, _ = run_lowered(src)
    assert values["c"] == "img[12]" and values["c2"] == "img[13]"
    assert values["node"] is None
    assert values["err"] == {"kind": "ValueError", "node": "entity", "message": "bad box"}
    assert "note" not in values and values["note2"] == "after"


def test_error_name_written_elsewhere_gets_a_home_version():
    src = """
image = "img"
err = {}
(err)len(n)
@try:
    (image, 13)crop(c)
    (c)entity(node)
@except err:
    node = None
(err)len(m)
"""
    values, c = run_lowered(src)
    assert values["err"]["node"] == "entity" and values["n"] == 0 and values["m"] == 3
    assert run_as_written(src)["m"] == 3


def test_def_has_its_own_scope_and_inlines():
    src = """
@def (image, box: int)expand(node):
    (image, box)crop(c)
    (c)entity(node)

c = "outer"
("img", 1)expand(a)
("img", box=3)expand(b)
"""
    values, compiled = run_lowered(src)
    assert values == {"a": "E(img[1])", "b": "E(img[3])", "c": "outer"}
    assert "expand__2__c" in write(compiled.lowered)
    assert run_as_written(src)["c"] == "outer"


def test_hints_stay_out_of_the_semantic_hash():
    plain = 'x = "img"\n(x, 1)crop(c)\n'
    hinted = 'x = "img"\n@hint retry=2\n(x, 1)crop(c)\n'
    meta = 'x = "img"\n@meta pos=(1, 2)\n(x, 1)crop(c)\n'
    a, b, m = (compile_source(s, [LIB]) for s in (plain, hinted, meta))
    assert a.semantic_hash == b.semantic_hash == m.semantic_hash
    assert a.full_hash != b.full_hash and a.full_hash == m.full_hash
    assert "@hint retry=2" in write(b.lowered)


def test_call_hook_sees_every_call():
    seen = []

    def hook(name, inputs, call):
        seen.append((name, dict(inputs)))
        return call()

    run_lowered('("a", 1)crop(c)\n', hook=hook)
    assert seen == [("crop", {"image": "a", "box": 1})]


def test_signature_file_format():
    lib = NodeLibrary("demo")

    @lib.node(outputs=["graph"], mutates=["graph"])
    def attach(graph: dict, node: str, weight: float = 1.0) -> dict:
        """Attach a node."""
        return graph

    data = library_to_json(lib)
    assert data == {
        "kirsig": 1,
        "library": "demo",
        "nodes": [
            {
                "name": "attach",
                "inputs": [
                    {"name": "graph", "type": "dict"},
                    {"name": "node", "type": "str"},
                    {"name": "weight", "type": "float", "default": 1.0},
                ],
                "outputs": [{"name": "graph", "type": "dict"}],
                "flags": {"mutates": ["graph"], "ordered": False},
                "doc": "Attach a node.",
            }
        ],
    }
    assert library_to_json(library_from_json(json.loads(json.dumps(data)))) == data


def test_use_resolves_signature_files(tmp_path):
    save_library(LIB, tmp_path / "t.kirsig.json")
    src = '@use "t" as g\n("img", 1)g.crop(c)\n'
    c = compile_source(src, sig_path=[tmp_path])
    assert c.env.resolve("g.crop").signature.name == "crop"
    with pytest.raises(KirCheckError, match="E002"):
        compile_source('@use "missing"\n', sig_path=[tmp_path])


BAD = {
    "E010": "(1)nope(x)\n",
    "E012": '("img")crop(c)\n',
    "E013": "a__b = 1\n",
    "E020": "(x, 1)crop(c)\n",
    "E021": "@def (a)f(b):\n    (a)branch(`y`, `n`)\n    y:\n        b = 1\n    n:\n\n(True)f(z)\n",
    "E030": "(True)branch(`y`, `missing`)\ny:\n",
    "E031": "(True)branch(`y`, `n`)\n(False)branch(`y`, `n`)\ny:\nn:\n",
    "E032": "()jump(`body`)\n([1])each(x, `body`)\nbody:\n",
    "E033": "@dataflow:\n    (a)identity(b)\n    (b)identity(a)\n",
    "E040": '("img", "one")crop(c)\n',
    "E041": "(1)branch(`y`, `n`)\ny:\nn:\n",
    "E050": "@def (a)f(b):\n    (a)f(b)\n",
    "E060": "@mode dataflow\n(True)branch(`y`, `n`)\ny:\nn:\n",
    "E061": "@dataflow:\n    y:\n        x = 1\n",
}


@pytest.mark.parametrize("code", sorted(BAD))
def test_each_check_fires(code):
    p = parse(BAD[code])
    found = {d.code for d in check(p, build_env(p, [LIB]))}
    assert code in found


def test_ambiguous_and_warnings():
    other = NodeLibrary("other")
    other.add("crop", lambda image, box: image, outputs=["crop"])
    p = parse('("img", 1)crop(c)\n')
    assert "E011" in {d.code for d in check(p, build_env(p, [LIB, other]))}
    warn = parse(
        "@def (x)f(y):\n    z = 1\n    y = x\n\n"
        "x = 1\n()parallel(`a`, `b`)\na:\n    y = 1\nb:\n    y = 2\nunused:\n"
    )
    found = check(warn, build_env(warn, [LIB]))
    assert {"W001", "W010", "W020"} <= {d.code for d in found}
    assert [d.message for d in found if d.code == "W020"] == ["'z' is written but never read"]
