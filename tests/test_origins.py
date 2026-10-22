"""Lowering provenance is a sidecar: it never changes KIR text or execution."""

import json
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from kohakunode import build_env, parse, write
from kohakunode.lower import full_hash, run_passes, semantic_hash
from kohakunode.origins import derive_origin, stamp_origins
from kohakunode.syntax.ast import (
    Assign,
    Call,
    Collect,
    Dataflow,
    Each,
    Namespace,
    Origin,
    Try,
    walk,
)

INLINE = """@def (x)inner(y):
    (x)identity(y)
@def (x)outer(y):
    (x)inner(y)
(1)outer(a)
(2)outer(b)
"""

EACH = """total = 0
([1, 2])each(item, index, `body`)
body:
    (total, item)add(total)
result = total
"""

VERSION_PASSES = ["order_dataflow", "inline", "expand_each", "version"]


def lower(program, names=None):
    return run_passes(program, build_env(program), names)


def test_stamp_paths_metadata_definition_and_source_lines():
    raw = parse(INLINE)
    raw.body[0].body[0].meta["node_id"] = "editor-node"
    stamped = stamp_origins(raw, "defs.kir")
    assert all(s.origin is None for s in walk(raw.body))
    assert stamped == raw
    assert stamped.body[0].origin == Origin("defs.kir", "body/0", 1, "inner")
    assert stamped.body[0].body[0].origin == Origin("defs.kir", "editor-node", 2, "inner")
    assert stamped.body[1].body[0].origin == Origin("defs.kir", "body/1/body/0", 4, "outer")
    assert stamped.body[2].origin == Origin("defs.kir", "body/2", 5)
    assert write(stamped) == write(raw)
    assert stamp_origins(stamped, "different.kir") == stamped
    assert [s.origin for s in walk(stamp_origins(stamped).body)] == [
        s.origin for s in walk(stamped.body)
    ]


def test_fallback_ids_are_format_independent_paths_including_try_handler():
    source = "@try:\n    x = 1\n@except err:\n    x = 2\n"
    a = stamp_origins(parse(source))
    b = stamp_origins(parse("\n\n" + source.replace("x =", "x  =")))
    ids = [s.origin.node_id for s in walk(a.body)]
    assert ids == ["body/0", "body/0/body/0", "body/0/handler/0"]
    assert ids == [s.origin.node_id for s in walk(b.body)]
    assert a.body[0].origin.line != b.body[0].origin.line
    assert a.body[0].origin.module == "<text>"


def test_order_dataflow_preserves_wrapper_and_reordered_child_origins():
    p = stamp_origins(parse("@dataflow:\n    y = x\n    x = 1\n"), "ordered.kir")
    result = lower(p, ["order_dataflow"])
    before, after = p.body[0], result.body[0]
    assert isinstance(after, Dataflow)
    assert after.origin == before.origin
    assert [s.target for s in after.body] == ["x", "y"]
    assert [s.origin for s in after.body] == [before.body[1].origin, before.body[0].origin]
    assert [s.target for s in before.body] == ["y", "x"]


def test_explicit_origins_are_preserved_and_immutable():
    p = parse("x = 1\ny = x\n")
    explicit = Origin("original.kir", "original", 42, "entry", generated="custom")
    p.body[0].origin = explicit
    stamped = stamp_origins(p, "new.kir")
    assert stamped.body[0].origin == explicit
    assert stamped.body[1].origin.module == "new.kir"
    with pytest.raises(FrozenInstanceError):
        stamped.body[0].origin.line = 100
    assert derive_origin(None, generated="new") is None
    derived = derive_origin(explicit, calls=(Origin("caller.kir", "call"),))
    assert derived.generated == "custom"
    assert derived.calls == (Origin("caller.kir", "call"),)
    assert explicit.calls == ()


def test_repeated_nested_inlining_retains_definition_and_distinct_call_chains():
    p = stamp_origins(parse(INLINE), "definitions.kir")
    # Definitions can come from a different module than their callers.
    for stmt in p.body[2:]:
        stmt.origin = replace(stmt.origin, module="main.kir")
    result = lower(p, ["order_dataflow", "inline"])
    calls = [s for s in walk(result.body) if isinstance(s, Call)]
    assert len(calls) == 2
    source = p.body[0].body[0].origin
    for i, call in enumerate(calls):
        origin = call.origin
        outer_call = p.body[i + 2].origin
        assert (origin.module, origin.node_id, origin.line, origin.definition) == (
            source.module,
            source.node_id,
            source.line,
            "inner",
        )
        assert origin.calls[0] == outer_call
        assert origin.calls[1].node_id == p.body[1].body[0].origin.node_id
        assert origin.calls[1].definition == "outer"
        assert all(site.calls == () for site in origin.calls)
        assert origin.generated is None
    assert calls[0].origin != calls[1].origin
    assert p.body[0].body[0].origin.calls == ()
    assignments = [s for s in result.body if isinstance(s, Assign)]
    assert len(assignments) == 8
    assert {s.origin.generated for s in assignments} == {"inline.arg", "inline.output"}
    assert all(s.origin.module in {"main.kir", "definitions.kir"} for s in assignments)
    nested_bindings = [s for s in assignments if s.origin.definition == "outer"]
    assert len(nested_bindings) == 4
    assert all(len(s.origin.calls) == 1 for s in nested_bindings)
    assert {s.origin.calls[0] for s in nested_bindings} == {
        p.body[2].origin,
        p.body[3].origin,
    }


def test_three_level_inline_ancestry_is_outermost_first():
    source = INLINE.replace("(1)outer(a)\n(2)outer(b)\n", "") + (
        "@def (x)top(y):\n" "    (x)outer(first)\n" "    (first)outer(y)\n" "(1)top(result)\n"
    )
    p = stamp_origins(parse(source))
    result = lower(p, ["order_dataflow", "inline"])
    calls = [s for s in result.body if isinstance(s, Call)]
    assert len(calls) == 2
    for index, call in enumerate(calls):
        assert [origin.node_id for origin in call.origin.calls] == [
            p.body[3].origin.node_id,
            p.body[2].body[index].origin.node_id,
            p.body[1].body[0].origin.node_id,
        ]
        assert call.origin.definition == "inner"
    assert calls[0].origin != calls[1].origin


@pytest.mark.parametrize("depth", [10, 20])
def test_nested_inline_origin_serialization_grows_linearly(depth):
    source = "@def (x)f0(y):\n    (x)identity(y)\n"
    source += "".join(f"@def (x)f{i}(y):\n    (x)f{i - 1}(y)\n" for i in range(1, depth))
    source += f"(1)f{depth - 1}(result)\n"
    p = stamp_origins(parse(source))
    result = lower(p, ["order_dataflow", "inline"])
    origin = next(s.origin for s in walk(result.body) if isinstance(s, Call))
    assert len(origin.calls) == depth
    assert [site.definition for site in origin.calls] == [
        None,
        *(f"f{i}" for i in range(depth - 1, 0, -1)),
    ]
    assert all(site.calls == () for site in origin.calls)
    encoded = json.dumps(asdict(origin))
    assert encoded.count('"module"') == depth + 1
    assert len(encoded) < 200 * (depth + 1)
    assert all(site.calls == () for s in walk(result.body) for site in s.origin.calls)


def test_derive_origin_makes_existing_and_appended_ancestry_shallow():
    outer = Origin("main.kir", "outer", 1)
    inner = Origin("lib.kir", "inner", 2, calls=(outer,))
    source = Origin("lib.kir", "body", 3, calls=(outer, inner))
    derived = derive_origin(source, calls=(inner,), generated="version.home")
    assert derived.calls == (outer, replace(inner, calls=()), replace(inner, calls=()))
    assert derived.generated == "version.home"
    assert inner.calls == (outer,)
    assert source.calls == (outer, inner)


def test_each_generated_operations_and_body_origins():
    p = stamp_origins(parse(EACH), "loop.kir")
    each = next(s for s in p.body if isinstance(s, Each))
    namespace = next(s for s in p.body if isinstance(s, Namespace))
    result = lower(p, ["expand_each"])
    stmts = list(walk(result.body))
    assert all(s.origin is not None for s in stmts)
    generated = [s for s in stmts if s.origin.generated is not None]
    assert {s.origin.generated for s in generated} == {
        "each.items",
        "each.init",
        "each.enter",
        "each.loop",
        "each.test",
        "each.branch",
        "each.item",
        "each.index",
        "each.next",
        "each.repeat",
        "each.done",
    }
    assert all(s.origin.node_id == each.origin.node_id for s in generated)
    assert all(s.origin.line == each.origin.line for s in generated)
    retained = next(s for s in stmts if isinstance(s, Namespace) and s.label == "body")
    assert retained.origin == namespace.origin
    add = next(s for s in stmts if isinstance(s, Call) and s.name == "add")
    assert add.origin == namespace.body[0].origin


def test_each_without_a_namespace_still_attributes_generated_body():
    p = stamp_origins(parse("([1])each(_, `body`)\n"))
    result = lower(p, ["expand_each"])
    body = next(s for s in walk(result.body) if isinstance(s, Namespace) and s.label == "body")
    assert body.origin.generated == "each.body"
    assert all(s.origin.node_id == p.body[0].origin.node_id for s in walk(result.body))


def test_version_home_assignments_retain_writer_origins():
    p = stamp_origins(parse(EACH))
    result = lower(p, VERSION_PASSES)
    stmts = list(walk(result.body))
    homes = [s for s in stmts if s.origin.generated == "version.home"]
    assert homes
    for stmt in homes:
        writer = next(
            s
            for s in stmts
            if (isinstance(s, Assign) and s.target == stmt.value.id)
            or (isinstance(s, Call) and stmt.value.id in s.outs)
        )
        assert stmt.origin == replace(writer.origin, generated="version.home")
    assert {s.origin.node_id for s in homes} >= {
        p.body[0].origin.node_id,
        p.body[2].body[0].origin.node_id,
    }


def test_version_handler_assignment_retains_try_origin():
    p = stamp_origins(
        parse(
            "err = {}\n"
            "@try:\n"
            "    (1)identity(x)\n"
            "@except err:\n"
            "    x = 2\n"
            "(err)identity(result)\n"
        ),
        "handler.kir",
    )
    result = lower(p, VERSION_PASSES)
    handler = next(s for s in walk(result.body) if isinstance(s, Try))
    assert handler.handler[0].origin == replace(p.body[1].origin, generated="version.handler")
    assert handler.handler[1].origin == p.body[1].handler[0].origin


def test_group_and_strip_meta_preserve_attribution():
    p = stamp_origins(parse('@meta node_id="x"\nx = 1\ny = x\n'))
    result = lower(p, ["group", "strip_meta"])
    wrapper = result.body[0]
    assert isinstance(wrapper, Dataflow)
    assert wrapper.origin == replace(p.body[0].origin, generated="group")
    assert [s.origin for s in wrapper.body] == [s.origin for s in p.body]
    assert all(s.meta == {} for s in walk(result.body))
    assert p.body[0].meta == {"node_id": "x"}


def test_origins_and_metadata_do_not_change_text_hashes_or_ast_equality():
    plain = parse(INLINE)
    stamped = stamp_origins(plain, "a.kir")
    metadata = parse(INLINE)
    for index, stmt in enumerate(walk(metadata.body)):
        stmt.meta = {"node_id": f"editor-{index}", "pos": (index, index)}
    metadata = stamp_origins(metadata, "b.kir")
    assert plain == stamped
    assert write(plain) == write(stamped)
    for hash_fn in (semantic_hash, full_hash):
        assert hash_fn(plain) == hash_fn(stamped) == hash_fn(metadata)
    lowered = [lower(p) for p in (plain, stamped, metadata)]
    assert write(lowered[0]) == write(lowered[1]) == write(lowered[2])
    for hash_fn in (semantic_hash, full_hash):
        assert hash_fn(lowered[0]) == hash_fn(lowered[1]) == hash_fn(lowered[2])
    assert all(s.origin is None for s in walk(lowered[0].body))
    assert all(s.origin is not None for s in walk(lowered[1].body))
    assert all(s.origin is not None for s in walk(lowered[2].body))


def test_collect_generated_origins_and_preserved_inline_ancestry():
    source = (
        "@def (items)gather(result):\n"
        "    (items)collect(item, `body`, value -> result)\n"
        "    body:\n"
        "        (item)identity(value)\n"
        "([1, 2])gather(a)\n"
        "([3, 4])gather(b)\n"
    )
    p = stamp_origins(parse(source), "collect.kir")
    collect_origin = p.body[0].body[0].origin
    expanded = lower(p, ["expand_collect"])
    generated = [s for s in walk(expanded.body) if s.origin.generated is not None]
    assert {s.origin.generated for s in generated} == {
        "collect.init",
        "collect.items",
        "collect.append",
        "collect.result",
    }
    assert all(s.origin.node_id == collect_origin.node_id for s in generated)
    assert all(s.origin.line == collect_origin.line for s in generated)
    assert all(s.origin.definition == "gather" for s in generated)
    for names in (
        ["order_dataflow", "inline", "strip_meta"],
        ["order_dataflow", "expand_collect", "inline", "strip_meta"],
        None,
    ):
        lowered = lower(p, names)
        copies = [s for s in walk(lowered.body) if s.origin.node_id == collect_origin.node_id]
        assert copies
        assert {s.origin.calls for s in copies} == {(p.body[1].origin,), (p.body[2].origin,)}
        assert all(s.origin is not None for s in walk(lowered.body))
    kept = lower(p, ["order_dataflow", "inline"])
    assert len([s for s in walk(kept.body) if isinstance(s, Collect)]) == 2
    assert write(lower(p)) == write(lower(parse(source)))
    assert semantic_hash(lower(p)) == semantic_hash(lower(parse(source)))
    assert full_hash(lower(p)) == full_hash(lower(parse(source)))


def test_inlined_each_retains_nested_ancestry_through_all_passes():
    source = (
        "@def (items)count(result):\n"
        "    total = 0\n"
        "    (items)each(item, `body`)\n"
        "    body:\n"
        "        (total, item)add(total)\n"
        "    result = total\n"
        "([1, 2])count(a)\n"
        "([3, 4])count(b)\n"
    )
    p = stamp_origins(parse(source))
    result = lower(p)
    each_id = p.body[0].body[1].origin.node_id
    each_ops = [s for s in walk(result.body) if s.origin.node_id == each_id]
    assert each_ops
    assert {s.origin.calls for s in each_ops} == {(p.body[1].origin,), (p.body[2].origin,)}
    assert all(s.origin.definition == "count" for s in each_ops)
    assert all(s.origin is not None for s in walk(result.body))
