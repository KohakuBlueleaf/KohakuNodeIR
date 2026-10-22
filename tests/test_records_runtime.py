"""Runtime records are nominal snapshots, never reflective views of host objects."""

import hashlib
import json
import math
import pickle
from dataclasses import FrozenInstanceError, replace

import pytest

from kohakunode.records import (
    RecordOperation,
    RecordValue,
    construct,
    decode_record,
    encode_record,
    project,
    replace_field,
)
from kohakunode.sig.records import RecordField, RecordSchema
from kohakunode.sig.types import parse_type
from kohakunode.syntax.ast import ANY

POINT = RecordSchema(
    "Point",
    (RecordField("x", parse_type("float")), RecordField("y", parse_type("float"))),
    "geometry.Point",
)
BOX = RecordSchema(
    "Box",
    (
        RecordField("point", parse_type("geometry.Point")),
        RecordField("labels", parse_type("list[str]"), True, []),
        RecordField("note", parse_type("str?"), True, None),
    ),
    "geometry.Box",
)
ANY_VALUE = RecordSchema("Value", (RecordField("value"),), "test.Value")


def schema_with(type_text):
    return RecordSchema("Typed", (RecordField("value", parse_type(type_text)),), "test.Typed")


def test_nominal_construct_project_replace_and_direct_constructor():
    point = construct(POINT, x=1, y=2.5)
    assert point.schema_id == "geometry.Point"
    assert project(POINT, point, "x") == 1
    assert point["y"] == 2.5
    assert RecordValue(POINT, y=2.5, x=1) == point
    updated = replace_field(POINT, point, "x", 9)
    assert updated["x"] == 9 and point["x"] == 1
    assert updated["y"] == point["y"]
    with pytest.raises(FrozenInstanceError):
        point.schema_id = "other.Point"
    with pytest.raises(FrozenInstanceError):
        point._fields = ()
    with pytest.raises(TypeError):
        point["x"] = 3
    with pytest.raises(AttributeError):
        _ = point.x
    with pytest.raises(AttributeError):
        _ = point.__dict__


def test_nested_record_and_nullable_default_are_not_implicit_dicts():
    point = construct(POINT, x=1, y=2)
    box = construct(BOX, point=point)
    assert box["point"] is point
    assert box["labels"] == [] and box["note"] is None
    assert replace_field(BOX, box, "note", "set")["note"] == "set"
    with pytest.raises(TypeError, match="point"):
        construct(BOX, point={"x": 1, "y": 2})
    other = replace(POINT, schema_id="other.Point")
    with pytest.raises(TypeError, match="point"):
        construct(BOX, point=construct(other, x=1, y=2))
    nullable = schema_with("str?")
    assert construct(nullable, value=None)["value"] is None
    with pytest.raises(TypeError, match="missing"):
        construct(nullable)
    with pytest.raises(TypeError, match="missing"):
        construct(BOX)


@pytest.mark.parametrize(
    ("type_text", "value"),
    [
        ("_", None),
        ("_", {"a": [1, True, None]}),
        ("bool", True),
        ("int", 2),
        ("float", 2),
        ("float", 2.5),
        ("None", None),
        ("str", "hello"),
        ("list", [None, 1]),
        ("dict", {"x": 1}),
        ("list[int]", []),
        ("list[int]", [1, 2]),
        ("dict[str, list[int]]", {"x": [1, 2]}),
        ("list[int | str?]", [1, "two", None]),
        ("int | str", "two"),
        ("int | str", 2),
        ("geometry.Point?", None),
    ],
)
def test_supported_recursive_types(type_text, value):
    assert construct(schema_with(type_text), value=value)["value"] == value


@pytest.mark.parametrize(
    ("type_text", "value"),
    [
        ("int", True),
        ("float", False),
        ("bool", 1),
        ("int", 1.5),
        ("str", None),
        ("None", "None"),
        ("list[int]", [1, True]),
        ("dict[str, list[int]]", {"x": [1, "two"]}),
        ("list[int | str?]", [False]),
        ("int | str", 2.5),
        ("geometry.Point?", {}),
    ],
)
def test_wrong_recursive_types(type_text, value):
    with pytest.raises(TypeError):
        construct(schema_with(type_text), value=value)


def test_nested_records_inside_generic_list_dict_and_union():
    point = construct(POINT, x=1, y=2)
    schema = schema_with("dict[str, list[geometry.Point | None]]")
    value = construct(schema, value={"points": [point, None]})
    assert value["value"] == {"points": [point, None]}
    with pytest.raises(TypeError):
        construct(schema, value={"points": [point, {"x": 1, "y": 2}]})


def test_input_output_update_and_default_aliases_are_isolated():
    shared = [1, {"nested": [2]}]
    payload = {"left": shared, "right": shared}
    value = construct(ANY_VALUE, value=payload)
    shared[1]["nested"].append(3)
    payload["new"] = "not stored"
    expected = {"left": [1, {"nested": [2]}], "right": [1, {"nested": [2]}]}
    assert value["value"] == expected
    projected = value["value"]
    projected["left"][1]["nested"].append(9)
    assert projected["right"][1]["nested"] == [2]
    assert value["value"] == expected
    replacement = {"changed": [4]}
    changed = replace_field(ANY_VALUE, value, "value", replacement)
    replacement["changed"].append(5)
    assert changed["value"] == {"changed": [4]}
    assert value["value"] == expected
    with pytest.raises(FrozenInstanceError):
        value._fields[0][1].items = ()

    defaults = {"x": [1]}
    schema = RecordSchema("Defaults", (RecordField("data", ANY, True, defaults),), "test.Defaults")
    defaults["x"].append(2)
    first, second = construct(schema), construct(schema)
    first["data"]["x"].append(3)
    assert first["data"] == second["data"] == {"x": [1]}


def test_unknown_missing_wrong_schema_and_conflicting_schema_shape():
    point = construct(POINT, x=1, y=2)
    with pytest.raises(TypeError, match="unknown"):
        construct(POINT, x=1, y=2, z=3)
    with pytest.raises(TypeError, match="missing"):
        construct(POINT, x=1)
    with pytest.raises(TypeError, match="expected record"):
        project(replace(POINT, schema_id="other.Point"), point, "x")
    with pytest.raises(TypeError, match="shape"):
        project(replace(POINT, fields=POINT.fields[:1]), point, "x")
    wrong_type = replace(POINT, fields=(RecordField("x", parse_type("str")), POINT.fields[1]))
    with pytest.raises(TypeError, match="wrong type"):
        project(wrong_type, point, "x")
    with pytest.raises(KeyError):
        project(POINT, point, "missing")
    with pytest.raises(KeyError):
        replace_field(POINT, point, "missing", 0)
    with pytest.raises(TypeError):
        replace_field(POINT, point, "x", True)
    with pytest.raises(ValueError, match="schema_id"):
        construct(replace(POINT, schema_id=""), x=1, y=2)


class PropertyTrap:
    touched = []

    @property
    def x(self):
        self.touched.append("x")
        raise AssertionError("projection reflected on a host property")

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError("record validation inspected a host object")

    def __deepcopy__(self, memo):
        self.touched.append("deepcopy")
        raise AssertionError("host deepcopy must never run")

    def __reduce__(self):
        self.touched.append("reduce")
        raise AssertionError("host pickle must never run")


class ListSubclass(list):
    def __iter__(self):
        raise AssertionError("must reject before iterating")


class DictSubclass(dict):
    def items(self):
        raise AssertionError("must reject before iterating")


class IntSubclass(int):
    pass


class FloatSubclass(float):
    pass


class StringSubclass(str):
    pass


class RecordSubclass(RecordValue):
    pass


@pytest.mark.parametrize(
    "value",
    [
        PropertyTrap(),
        object(),
        (),
        (1, 2),
        {1, 2},
        frozenset({1}),
        b"bytes",
        bytearray(b"bytes"),
        ListSubclass([1]),
        DictSubclass(x=1),
        IntSubclass(1),
        FloatSubclass(1.5),
        StringSubclass("text"),
        {1: "not a string key"},
        {StringSubclass("key"): 1},
        RecordSubclass(POINT, x=1, y=2),
    ],
    ids=lambda _: "nonportable",
)
def test_reject_nonportable_values_without_reflection(value):
    with pytest.raises(TypeError):
        construct(ANY_VALUE, value=value)
    with pytest.raises(TypeError):
        construct(ANY_VALUE, value=[{"nested": value}])
    assert PropertyTrap.touched == []


def test_projection_rejects_host_objects_and_subclasses_without_reflection():
    trap = PropertyTrap()
    for record in (trap, {"x": 1, "y": 2}, RecordSubclass(POINT, x=1, y=2)):
        with pytest.raises(TypeError, match="exact RecordValue"):
            project(POINT, record, "x")
        with pytest.raises(TypeError, match="exact RecordValue"):
            replace_field(POINT, record, "x", 3)
    assert PropertyTrap.touched == []


@pytest.mark.parametrize("number", [math.inf, -math.inf, math.nan])
def test_nonfinite_floats_are_not_portable_even_under_any(number):
    with pytest.raises(ValueError, match="finite"):
        construct(ANY_VALUE, value=number)
    with pytest.raises(ValueError, match="finite"):
        construct(ANY_VALUE, value={"nested": [number]})


def test_container_cycles_rejected_but_shared_acyclic_data_allowed():
    array = []
    array.append(array)
    mapping = {}
    mapping["self"] = mapping
    mixed = {"array": []}
    mixed["array"].append(mixed)
    for cycle in (array, mapping, mixed):
        with pytest.raises(ValueError, match="cycles"):
            construct(ANY_VALUE, value=cycle)
    shared = {"x": [1]}
    assert construct(ANY_VALUE, value=[shared, shared])["value"] == [shared, shared]


def test_defaults_are_literal_not_record_values():
    point = construct(POINT, x=1, y=2)
    for value in (point, [point], {"point": point}):
        with pytest.raises(ValueError, match="defaults"):
            RecordField("point", ANY, True, value)


def test_codec_roundtrip_nested_records_and_tag_shaped_user_dicts():
    point = construct(POINT, x=1, y=2)
    payload = {
        "point": point,
        "looks_like_record": {"$kir": "record", "schema": "geometry.Point", "fields": {"x": 9}},
        "looks_like_list": {"$kir": "list", "items": [1, 2]},
        "looks_like_dict": {"$kir": "dict", "items": {}},
        "nested": [None, True, 4, 2.5, "text", [point]],
    }
    record = construct(ANY_VALUE, value=payload)
    encoded = encode_record(record)
    assert encoded["$kir"] == "record" and encoded["schema"] == "test.Value"
    assert encoded["fields"]["value"]["$kir"] == "dict"
    schemas = {schema.schema_id: schema for schema in (ANY_VALUE, POINT)}
    decoded = decode_record(json.loads(json.dumps(encoded)), schemas)
    assert decoded == record
    assert decoded["value"] == payload
    encoded["fields"]["value"]["items"].clear()
    assert record["value"] == payload
    assert decoded.__togeari_digest__() == record.__togeari_digest__()


@pytest.mark.parametrize(
    "encoded",
    [
        None,
        [],
        {},
        {"$kir": "unknown"},
        {"$kir": "list", "items": []},
        {"$kir": "dict", "items": {}},
        {"$kir": "record", "schema": "missing", "fields": {}},
        {"$kir": "record", "schema": "test.Value", "fields": {}},
        {"$kir": "record", "schema": "test.Value", "fields": {"value": 1, "extra": 2}},
        {"$kir": "record", "schema": "test.Value", "fields": {"value": []}},
        {"$kir": "record", "schema": "test.Value", "fields": {"value": math.nan}},
        {"$kir": "record", "schema": "test.Value", "fields": {"value": object()}},
        {"$kir": "record", "schema": 1, "fields": {}},
        {"$kir": "record", "schema": "test.Value", "fields": [], "extra": 1},
        {"$kir": "record", "schema": "test.Value", "fields": DictSubclass(value=1)},
        {"$kir": "record", "schema": "test.Value", "fields": {1: 2}},
        DictSubclass({"$kir": "record", "schema": "test.Value", "fields": {"value": 1}}),
    ],
)
def test_codec_rejects_invalid_shapes_and_domain(encoded):
    with pytest.raises((TypeError, ValueError)):
        decode_record(encoded, {ANY_VALUE.schema_id: ANY_VALUE})


def test_codec_validates_field_types_registry_identity_and_cycles():
    encoded = encode_record(construct(POINT, x=1, y=2))
    encoded["fields"]["x"] = True
    with pytest.raises(TypeError):
        decode_record(encoded, {POINT.schema_id: POINT})
    with pytest.raises(ValueError, match="registry"):
        decode_record(encoded, {POINT.schema_id: replace(POINT, schema_id="wrong.Point")})
    cycle = {"$kir": "list", "items": []}
    cycle["items"].append(cycle)
    with pytest.raises(ValueError, match="cycles"):
        decode_record(cycle, {})
    with pytest.raises(TypeError):
        encode_record(PropertyTrap())
    assert PropertyTrap.touched == []


def test_digest_is_nominal_canonical_and_type_sensitive():
    a = construct(ANY_VALUE, value={"a": [1, 2], "b": "unicode \u2603"})
    b = construct(ANY_VALUE, value={"b": "unicode \u2603", "a": [1, 2]})
    assert a == b and hash(a) == hash(b)
    assert a.__togeari_digest__() == b.__togeari_digest__()
    assert type(a.__togeari_digest__()) is bytes and len(a.__togeari_digest__()) == 32
    other = construct(replace(ANY_VALUE, schema_id="other.Value"), value=a["value"])
    assert other != a and other.__togeari_digest__() != a.__togeari_digest__()
    variants = [construct(ANY_VALUE, value=value) for value in (1, True, 1.0, "1", [1], {"x": 1})]
    assert len({value.__togeari_digest__() for value in variants}) == len(variants)
    assert len(set(variants)) == len(variants)
    assert a != a["value"]


def test_canonical_digest_v1_known_encoding_and_container_boundaries():
    value = construct(ANY_VALUE, value={"x": [1, True, None, ""]})
    canonical = b"r1:s10:test.Values5:valued1:s1:xl4:i1:1b1ns0:"
    assert (
        value.__togeari_digest__() == hashlib.sha256(b"kohakunode.record.v1\0" + canonical).digest()
    )
    variants = [
        ["a", "bc"],
        ["ab", "c"],
        {"a": "bc"},
        {"ab": "c"},
        {"x": []},
        {"x": {}},
        "\ud800",
        "\\ud800",
    ]
    assert len({construct(ANY_VALUE, value=v).__togeari_digest__() for v in variants}) == len(
        variants
    )


def test_empty_record_codec_and_descriptor():
    schema = RecordSchema("Empty", (), "test.Empty")
    record = RecordOperation(schema, "make")()
    assert encode_record(record) == {"$kir": "record", "schema": "test.Empty", "fields": {}}
    assert decode_record(encode_record(record), {schema.schema_id: schema}) == record
    with pytest.raises(TypeError, match="unknown"):
        construct(schema, extra=None)


def test_reinitialization_cannot_mutate_records_or_nested_aliases():
    point = construct(POINT, x=1, y=2)
    box = construct(BOX, point=point)
    original_digest = box.__togeari_digest__()
    values = {point: "stored"}
    with pytest.raises(TypeError, match="reinitialized"):
        point.__init__(POINT, x=99, y=2)
    with pytest.raises(TypeError, match="validated construction"):
        point.__setstate__(["other.Point", (), POINT])
    assert point["x"] == box["point"]["x"] == 1
    assert box.__togeari_digest__() == original_digest
    assert values[point] == "stored"


def test_private_container_reinitialization_cannot_mutate_shared_records():
    nested = construct(ANY_VALUE, value={"list": [1]})
    parent = construct(ANY_VALUE, value=nested)
    original_digest = parent.__togeari_digest__()
    stored = {nested: "kept"}
    dictionary = nested._fields[0][1]
    sequence = dictionary.items[0][1]
    for container in (dictionary, sequence):
        with pytest.raises(TypeError, match="reinitialized"):
            container.__init__(())
        with pytest.raises(TypeError, match="cannot be replaced"):
            container.__setstate__([()])
    assert nested["value"] == parent["value"]["value"] == {"list": [1]}
    assert parent.__togeari_digest__() == original_digest
    assert stored[nested] == "kept"
    assert pickle.loads(pickle.dumps(parent)) == parent


@pytest.mark.parametrize("sign", [1, -1])
def test_arbitrary_size_integers_digest_equality_pickle_and_direct_codec(sign):
    huge = sign * 10**5000
    value = construct(ANY_VALUE, value={"huge": [huge]})
    equal = construct(ANY_VALUE, value={"huge": [huge]})
    assert equal == value
    assert hash(equal) == hash(value)
    assert equal.__togeari_digest__() == value.__togeari_digest__()
    assert construct(ANY_VALUE, value={"huge": [-huge]}) != value
    data = encode_record(value)
    decoded = decode_record(data, {ANY_VALUE.schema_id: ANY_VALUE})
    assert decoded == value and decoded["value"]["huge"] == [huge]
    assert pickle.loads(pickle.dumps(value)) == value


def test_pickle_roundtrip_values_defaults_and_operation_descriptors():
    point = construct(POINT, x=1, y=2)
    box = construct(BOX, point=point, labels=["before"])
    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
        rebuilt = pickle.loads(pickle.dumps(box, protocol=protocol))
        assert rebuilt == box and rebuilt.__togeari_digest__() == box.__togeari_digest__()
        rebuilt["labels"].append("not stored")
        assert box["labels"] == rebuilt["labels"] == ["before"]
        make = pickle.loads(pickle.dumps(RecordOperation(BOX, "make"), protocol=protocol))
        assert make(point=point)["labels"] == []
        get = pickle.loads(pickle.dumps(RecordOperation(POINT, "get", "x"), protocol=protocol))
        assert get(record=point) == 1
        update = pickle.loads(pickle.dumps(RecordOperation(POINT, "with", "x"), protocol=protocol))
        assert update(record=point, value=3)["x"] == 3


def test_operations_validate_arguments_and_keyword_field_collisions():
    make = RecordOperation(POINT, "make")
    point = make(1, y=2)
    assert RecordOperation(POINT, "get", "x")(point) == 1
    assert RecordOperation(POINT, "with", "y")(point, 3)["y"] == 3
    for args, kwargs in [((1, 2, 3), {}), ((1,), {"x": 2, "y": 3}), ((), {"x": 1})]:
        with pytest.raises(TypeError):
            make(*args, **kwargs)
    with pytest.raises(TypeError):
        RecordOperation(POINT, "get", "x")(record=point, extra=1)
    with pytest.raises(TypeError):
        RecordOperation(POINT, "with", "x")(point)
    for kind, name in [("unknown", None), ("make", "x"), ("get", "missing")]:
        with pytest.raises((ValueError, KeyError)):
            RecordOperation(POINT, kind, name)
    schema = RecordSchema(
        "Collision",
        tuple(RecordField(name) for name in ("schema", "record", "value", "self")),
        "test.Collision",
    )
    values = {"schema": 1, "record": 2, "value": 3, "self": 4}
    result = RecordOperation(schema, "make")(**values)
    assert result == construct(schema, **values)
    assert result["schema"] == 1 and result["self"] == 4
