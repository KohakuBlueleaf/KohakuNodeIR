"""Standard emit is an ordered call with a separate committed reference sidecar."""

import copy
import pickle
from dataclasses import FrozenInstanceError, replace

import pytest

from kohakunode import (
    Event,
    EventDeliveryError,
    Interpreter,
    NodeFailure,
    build_env,
    compile_source,
    decode_portable,
    encode_portable,
    parse,
    run,
    write,
)
from kohakunode.graph import from_graph, to_graph
from kohakunode.records import construct, decode_record, encode_record
from kohakunode.sig import STD, Library, NodeLibrary, Port, Signature
from kohakunode.sig.records import FrozenDict
from kohakunode.sig.std import EMIT_IMPL, EMIT_SIGNATURE, is_standard_emit


def interpreter(source, *, lowered=False, libraries=(), **kwargs):
    if lowered:
        compiled = compile_source(source, list(libraries))
        return Interpreter(compiled.lowered, compiled.env, **kwargs)
    program = parse(source)
    return Interpreter(program, build_env(program, list(libraries)), **kwargs)


@pytest.mark.parametrize(
    "value",
    [
        None,
        False,
        1,
        1.5,
        "text",
        [],
        {},
        [1, {"x": None}],
        {"$kir": "record", "schema": "fake", "fields": {}},
    ],
)
def test_portable_codec_snapshots_and_tags_every_container(value):
    encoded = encode_portable(value)
    assert decode_portable(encoded) == value
    event = Event.capture("topic", value)
    assert event.to_dict() == {"topic": "topic", "payload": encoded}
    assert event.decode() == value
    assert pickle.loads(pickle.dumps(event)) == event
    assert copy.deepcopy(event) == event
    if isinstance(value, (list, dict)):
        assert encoded["$kir"] == type(value).__name__


def test_record_payload_requires_no_registry_until_decoded():
    lib = NodeLibrary("geometry")
    schema = lib.record("Point", [("x", "int")])
    record = construct(schema, x=1)
    event = Event.capture("point", {"items": [record]})
    assert Event(**{"topic": "point", "encoded_payload": event.to_dict()["payload"]}) == event
    with pytest.raises(ValueError, match="unknown record schema"):
        event.decode()
    assert event.decode({schema.schema_id: schema}) == {"items": [record]}
    assert decode_record(encode_record(record), {schema.schema_id: schema}) == record
    with pytest.raises(TypeError):
        encode_record([record])
    with pytest.raises(TypeError):
        decode_record(encode_portable([record]), {schema.schema_id: schema})


def test_event_is_deeply_immutable_and_transport_copies_are_detached():
    value = {"items": [1]}
    event = Event.capture("topic", value)
    value["items"].append(2)
    detached = event.to_dict()
    detached["payload"]["items"]["items"]["items"].append(3)
    assert event.decode() == {"items": [1]}
    assert isinstance(event.payload, FrozenDict)
    for action in (
        lambda: event.__init__("changed", None),
        lambda: event.__setstate__({"topic": "changed"}),
        lambda: event.payload.__init__(()),
    ):
        with pytest.raises(FrozenInstanceError):
            action()
    assert not hasattr(event, "__dict__")
    assert hash(event) == hash(copy.deepcopy(event))


@pytest.mark.parametrize("a,b", [(True, 1), (1, 1.0), ([True], [1]), ({"a": 1}, {"a": True})])
def test_event_equality_is_type_sensitive(a, b):
    assert Event.capture("topic", a) != Event.capture("topic", b)


def test_event_large_integer_does_not_need_decimal_json_conversion():
    large = 1 << 20000
    event = Event.capture("large", [large])
    assert event.decode() == [large]
    assert event == copy.deepcopy(event)
    assert hash(event) == hash(copy.deepcopy(event))


class Opaque:
    @property
    def payload(self):
        raise AssertionError("properties must never be evaluated")


class ListSubclass(list):
    pass


class StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "value",
    [
        Opaque(),
        ListSubclass([1]),
        StringSubclass("x"),
        (1,),
        {1: "x"},
        float("nan"),
        float("inf"),
        {"x": object()},
    ],
)
def test_nonportable_payload_rejected_without_reflection(value):
    with pytest.raises((TypeError, ValueError)):
        Event.capture("topic", value)


def test_cyclic_payload_rejected():
    value = []
    value.append(value)
    with pytest.raises(ValueError, match="cycles"):
        Event.capture("topic", value)


@pytest.mark.parametrize(
    "encoded",
    [
        [],
        {},
        {"$kir": "list", "items": ()},
        {"$kir": "dict", "items": {1: None}},
        {"$kir": "record", "schema": 1, "fields": {}},
        {"$kir": "record", "schema": "x", "fields": {}, "extra": 1},
    ],
)
def test_event_encoded_constructor_rejects_malformed_tags(encoded):
    with pytest.raises((TypeError, ValueError)):
        Event("topic", encoded)


@pytest.mark.parametrize("lowered", [False, True])
def test_direct_lowered_emit_prefix_order_and_retained_values(lowered):
    received = []
    interp = interpreter(
        '("first", [1])emit()\n("second", {"x": True})emit()\nresult = 7\n',
        lowered=lowered,
        events=received.append,
    )
    interp.run()
    assert interp.source_values() == {"result": 7}
    assert (
        received
        == interp.events
        == [Event.capture("first", [1]), Event.capture("second", {"x": True})]
    )
    assert interp.events[0] is received[0]


@pytest.mark.parametrize("topic", [None, 1, StringSubclass("topic")])
def test_topic_requires_exact_string(topic):
    with pytest.raises(TypeError, match="exact string"):
        Event.capture(topic, None)


@pytest.mark.parametrize("mode", ["skip", "once", "twice"])
def test_hook_does_not_bypass_or_duplicate_semantic_event(mode):
    calls = []

    def hook(name, inputs, call):
        calls.append((name, inputs))
        if mode != "skip":
            assert call() is None
        if mode == "twice":
            assert call() is None
        return None

    interp = interpreter('("topic", 1)emit()\n', hook=hook)
    interp.run()
    assert len(calls) == 1
    assert interp.events == [Event.capture("topic", 1)]


def test_payload_is_captured_before_hook_mutates_input():
    def hook(name, inputs, call):
        inputs["payload"]["items"].append(2)
        return None

    interp = interpreter('("topic", {"items": [1]})emit()\n', hook=hook)
    interp.run()
    assert interp.events[0].decode() == {"items": [1]}


@pytest.mark.parametrize("mode", ["direct", "thunk", "recorded_error", "impossible_success"])
def test_invalid_payload_is_hook_visible_and_never_publishes(mode):
    source = '@def (payload)main():\n    @try:\n        ("topic", payload)emit()\n    @except error:\n        handled = True\n'
    observed = []

    def hook(name, inputs, call):
        observed.append(name)
        if mode == "recorded_error":
            raise TypeError("recorded unsupported payload")
        if mode == "impossible_success":
            return None
        return call()

    interp = interpreter(source, hook=None if mode == "direct" else hook)
    assert interp.call("main", {"payload": Opaque()}) == {}
    assert interp.events == []
    assert observed == ([] if mode == "direct" else ["emit"])


def test_recorded_failure_of_valid_emit_does_not_publish():
    def hook(name, inputs, call):
        raise ValueError("recorded failure")

    interp = interpreter('("topic", 1)emit()\n', hook=hook)
    with pytest.raises(NodeFailure):
        interp.run()
    assert interp.events == []


@pytest.mark.parametrize("lowered", [False, True])
def test_later_catchable_failure_keeps_committed_prefix(lowered):
    interp = interpreter(
        '@try:\n    ("before", 1)emit()\n    (1, 0)div(value)\n    ("unreached", 2)emit()\n@except error:\n    ("handler", 3)emit()\n',
        lowered=lowered,
    )
    interp.run()
    assert interp.events == [Event.capture("before", 1), Event.capture("handler", 3)]
    assert interp.source_values()["error"]["kind"] == "ZeroDivisionError"


@pytest.mark.parametrize("lowered", [False, True])
def test_delivery_failure_is_fatal_after_commit_not_catchable(lowered):
    def sink(event):
        raise ValueError("sink failed")

    interp = interpreter(
        '@try:\n    ("committed", 1)emit()\n@except error:\n    handled = True\n',
        lowered=lowered,
        events=sink,
    )
    with pytest.raises(EventDeliveryError, match="sink failed") as failure:
        interp.run()
    assert not isinstance(failure.value, NodeFailure)
    assert isinstance(failure.value.__cause__, ValueError)
    assert interp.events == [Event.capture("committed", 1)]
    assert "handled" not in interp.source_values()


def test_public_invocations_reset_sidecar_but_nested_definitions_do_not():
    interp = interpreter(
        '@def (x)child():\n    ("child", x)emit()\n@def ()parent():\n    (1)child()\n    (2)child()\n()parent()\n'
    )
    interp.run()
    assert interp.events == [Event.capture("child", 1), Event.capture("child", 2)]
    interp.call("child", {"x": 3})
    assert interp.events == [Event.capture("child", 3)]
    interp.call("parent", {})
    assert interp.events == [Event.capture("child", 1), Event.capture("child", 2)]
    interp.run()
    assert len(interp.events) == 2


@pytest.mark.parametrize("lowered", [False, True])
def test_each_collect_emit_logical_order(lowered):
    source = '([1, 2])collect(item, `body`, item -> results)\nbody:\n    ("item", item)emit()\n'
    interp = interpreter(source, lowered=lowered)
    interp.run()
    assert interp.source_values()["results"] == [1, 2]
    assert interp.events == [Event.capture("item", 1), Event.capture("item", 2)]


@pytest.mark.parametrize("lowered", [False, True])
def test_each_repeated_equal_payloads_remain_distinct_events(lowered):
    interp = interpreter(
        '([1, 1])each(item, `body`)\nbody:\n    ("item", item)emit()\n', lowered=lowered
    )
    interp.run()
    assert interp.events == [Event.capture("item", 1), Event.capture("item", 1)]
    assert interp.events[0] is not interp.events[1]


def test_uncaught_later_failure_retains_prefix():
    interp = interpreter('("before", 1)emit()\n(1, 0)div(result)\n')
    with pytest.raises(NodeFailure):
        interp.run()
    assert interp.events == [Event.capture("before", 1)]


def test_imported_subgraph_events_retain_sequence():
    compiled = compile_source(
        '@import "events.kir" as e\n(1)e.publish()\n(2)e.publish()\n',
        modules={"events.kir": '@export publish\n@def (x)publish():\n    ("value", x)emit()\n'},
    )
    interp = Interpreter(compiled.lowered, compiled.env)
    interp.run()
    assert interp.events == [Event.capture("value", 1), Event.capture("value", 2)]


def test_authentic_std_alias_emits_but_host_and_definition_shadow_do_not():
    aliased = interpreter('@use "kir.std" as std\n("topic", 1)std.emit()\n')
    aliased.run()
    assert aliased.events == [Event.capture("topic", 1)]
    host = Library("host")
    host.add_signature(
        Signature("emit", (Port("topic"), Port("payload")), (), ordered=True), lambda **kwargs: None
    )
    for interp in (
        interpreter('("topic", 1)emit()\n', libraries=[host]),
        interpreter('@def (topic, payload)emit():\n    value = payload\n("topic", 1)emit()\n'),
        interpreter('("topic", 1)emit()\n', nodes={"emit": lambda **kwargs: None}),
    ):
        interp.run()
        assert interp.events == []
    assert is_standard_emit(STD, EMIT_SIGNATURE, EMIT_IMPL)
    assert not is_standard_emit(STD, replace(EMIT_SIGNATURE), EMIT_IMPL)
    assert not is_standard_emit(host, EMIT_SIGNATURE, EMIT_IMPL)
    assert not is_standard_emit(STD, EMIT_SIGNATURE, lambda **kwargs: None)


def test_emit_remains_ordinary_visible_graph_call_and_helper_callback():
    program = parse('("topic", [1])emit()\n')
    env = build_env(program)
    signature = env.resolve("emit").signature
    assert signature.ordered and signature.mutates == () and signature.outputs == ()
    assert [port.name for port in signature.inputs] == ["topic", "payload"]
    graph = to_graph(program, env)
    node = graph["graphs"][0]["nodes"][0]
    assert node["kind"] == "call" and node["name"] == "emit" and node["outputs"] == []
    assert write(from_graph(graph, with_meta=False)) == write(program)
    received = []
    assert run(program, env, events=received.append) == {}
    assert received == [Event.capture("topic", [1])]
