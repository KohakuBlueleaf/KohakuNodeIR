from pathlib import Path

import pytest

from kohakunode.errors import KirSyntaxError
from kohakunode.syntax import parse, write
from kohakunode.syntax.ast import Branch, Call, Each, Literal, Name, Switch, Try

CORPUS = Path(__file__).parent / "corpus"
V1_PARSE_ERRORS = {"converted2_api_l2.kir", "subgraph_demo_l3.kir"}


def corpus_files():
    return sorted(p for p in CORPUS.rglob("*.kir") if p.name not in V1_PARSE_ERRORS)


@pytest.mark.parametrize("path", corpus_files(), ids=lambda p: p.name)
def test_write_is_canonical_and_round_trips(path):
    program = parse(path.read_text(encoding="utf-8"))
    text = write(program)
    again = parse(text)
    assert again.body == program.body
    assert again.uses == program.uses
    assert write(again) == text


def test_v2_syntax():
    src = """@use "gbc.nodes" as g
@use "kir.std"

@def (image: Image, box: Box, budget: int = 8)expand(node: Node?):
    @try:
        (image, box)crop(crop_img)
        @hint retry=2 max_wait_ms=5
        (crop_img, box, max_tokens=64)g.entity(node)
    @except err:
        node = None

(frontier)each(b, i, `body`)
body:
    (x)switch(1=>`a`, "two"=>`b`, _=>`c`)
"""
    p = parse(src)
    assert [u.alias for u in p.uses] == ["g", None]
    d = p.body[0]
    assert [x.name for x in d.params] == ["image", "box", "budget"]
    assert d.params[2].default == Literal(8)
    t = d.body[0]
    assert isinstance(t, Try) and t.error_name == "err"
    call = t.body[1]
    assert isinstance(call, Call) and call.name == "g.entity"
    assert call.hint == {"retry": 2, "max_wait_ms": 5}
    assert call.args[2].key == "max_tokens"
    each = p.body[1]
    assert isinstance(each, Each) and (each.item, each.index, each.label) == ("b", "i", "body")
    sw = p.body[2].body[0]
    assert isinstance(sw, Switch) and sw.cases == [(1, "a"), ("two", "b")] and sw.default == "c"
    assert parse(write(p)).body == p.body


def test_builtin_shapes():
    p = parse("(ok)branch(`y`, `n`)\ny:\nn:\n")
    assert p.body[0] == Branch(Name("ok"), "y", "n")
    with pytest.raises(KirSyntaxError):
        parse("(a, b)branch(`y`, `n`)\n")
    with pytest.raises(KirSyntaxError):
        parse("(xs)each(`body`)\n")
    with pytest.raises(KirSyntaxError):
        parse("(x)f(`label`)\n")
    with pytest.raises(KirSyntaxError):
        parse('(x)f(y)\n@use "lib"\n')


def test_keywords_end_at_word_boundaries():
    p = parse('@use "x" as g\n(Nonesuch, Truex)f(_tmp, _)\ny: int | None = None\n')
    call = p.body[0]
    assert [a.value for a in call.args] == [Name("Nonesuch"), Name("Truex")]
    assert call.outs == ["_tmp", None]
    assert write(p).splitlines()[-1] == "y: int | None = None"
    for bad in (
        '@use "x" asg\n',
        "@metax=1\nx = 1\n",
        "@meta a=Truex=1\nx = 1\n",
        "True = 1\n",
        "(x)f(None)\n",
        "_ = 1\n",
    ):
        with pytest.raises(KirSyntaxError):
            parse(bad)


def test_comment_lines_do_not_indent():
    p = parse(
        "x = 1\n    # indented comment\ny = 2\nns:\n    a = 1\n# outdented comment\n    b = 2\n"
    )
    assert [type(s).__name__ for s in p.body] == ["Assign", "Assign", "Namespace"]
    assert len(p.body[2].body) == 2
    assert parse("\n# c\n\nx = 1\n").body == parse("x = 1\n").body
    for bad in ("    x = 1\n", "\n\n    x = 1\n", "# c\n  x = 1\n"):
        with pytest.raises(KirSyntaxError):
            parse(bad)
    with pytest.raises(KirSyntaxError) as exc:
        parse("ns:\n    x = 1\n  y = 2\n")
    assert (exc.value.line, exc.value.column) == (3, 3)
    assert parse("# c\rx = 1\r\ny = 2").body == parse("# c\nx = 1\ny = 2\n").body


def test_literal_edges():
    p = parse("@meta pos=() size=(3,) at=(1, 2)\nx = 1\n")
    assert p.body[0].meta == {"pos": (), "size": (3,), "at": (1, 2)}
    assert parse(write(p)).body == p.body
    for bad in ("x = 1e999\n", "x = ١٢\n"):
        with pytest.raises(KirSyntaxError):
            parse(bad)
