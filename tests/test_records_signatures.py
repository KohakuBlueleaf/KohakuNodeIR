"""Record schemas derive ordinary signatures and portable trusted operations."""

import copy
import json
import pickle
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from kohakunode.errors import KirSignatureError
from kohakunode.records import RecordOperation
from kohakunode.sig import (
    Library,
    NodeLibrary,
    Port,
    RecordField,
    RecordSchema,
    Signature,
    library_from_json,
    library_to_json,
    load_library,
    save_library,
)
from kohakunode.sig.records import (
    FrozenDict,
    FrozenList,
    portable_default_equal,
    record_schema_equal,
    thaw_default,
)
from kohakunode.sig.types import parse_type
from kohakunode.syntax.ast import ANY, TypeExpr


def point_library():
    lib = NodeLibrary("geometry")
    lib.record("Point", [("x", "float"), ("y", "float", 0), ("label", "str?", None)])
    return lib


def test_record_interfaces_and_generated_signatures():
    lib = point_library()
    schema = lib.records["Point"]
    assert schema.schema_id == "geometry.Point"
    assert list(lib.signatures) == [
        "Point.make",
        "Point.get.x",
        "Point.with.x",
        "Point.get.y",
        "Point.with.y",
        "Point.get.label",
        "Point.with.label",
    ]
    nominal = TypeExpr("name", "geometry.Point")
    make = lib.signatures["Point.make"]
    assert [p.name for p in make.inputs] == ["x", "y", "label"]
    assert [p.required for p in make.inputs] == [True, False, False]
    assert make.inputs[1].default == 0 and make.inputs[2].default is None
    assert make.outputs == (Port("record", nominal),)
    getter = lib.signatures["Point.get.x"]
    assert getter.inputs == (Port("record", nominal),)
    assert getter.outputs == (Port("value", TypeExpr("name", "float")),)
    update = lib.signatures["Point.with.x"]
    assert update.inputs == (Port("record", nominal), Port("value", TypeExpr("name", "float")))
    assert update.outputs == (Port("record", nominal),)
    assert all(not sig.mutates and not sig.ordered for sig in lib.signatures.values())
    assert all(isinstance(impl, RecordOperation) for impl in lib.impls.values())
    assert lib.impls["Point.make"].schema is schema
    assert lib.impls["Point.get.x"].field == "x"
    assert lib.impls["Point.with.x"].kind == "with"


def test_library_positional_compatibility_and_empty_records():
    sig = Signature("host", (), ())
    lib = Library("geometry", {"host": sig}, {})
    assert lib.records == {}
    schema = lib.add_record("Empty", [])
    assert schema.fields == ()
    assert lib.signatures["Empty.make"].inputs == ()
    other = Library("geometry", records={"Empty": RecordSchema("Empty", ())})
    assert other.records["Empty"] == schema
    assert list(other.signatures) == ["Empty.make"]


def test_qualification_local_forward_external_and_nested_types():
    lib = NodeLibrary("geometry")
    schema = lib.record(
        "Shape",
        [
            ("point", "Point"),
            ("points", "list[Point]"),
            ("by_name", "dict[str, Point?]"),
            ("external", "other.Material | None"),
        ],
    )
    assert [f.type for f in schema.fields] == [
        parse_type("geometry.Point"),
        parse_type("list[geometry.Point]"),
        parse_type("dict[str, geometry.Point?]"),
        parse_type("other.Material | None"),
    ]
    lib.record("Point", [("x", "float")])
    assert lib.signatures["Shape.make"].inputs[0].type == parse_type("geometry.Point")


def test_defaults_are_deeply_immutable_copied_and_pickle_safe():
    source = {"points": [1, 2]}
    field = RecordField("options", parse_type("dict[str, list[int]]"), True, source)
    schema = Library("geometry").add_record("Options", [field])
    source["points"].append(3)
    default = schema.fields[0].default
    assert isinstance(default, FrozenDict)
    assert isinstance(default.items[0][1], FrozenList)
    assert thaw_default(default) == {"points": [1, 2]}
    thawed = thaw_default(default)
    thawed["points"].append(4)
    assert thaw_default(default) == {"points": [1, 2]}
    assert pickle.loads(pickle.dumps(schema)) == schema
    assert hash(schema) == hash(pickle.loads(pickle.dumps(schema)))
    with pytest.raises(FrozenInstanceError):
        schema.name = "Other"
    with pytest.raises(FrozenInstanceError):
        schema.fields[0].default = None
    with pytest.raises(FrozenInstanceError):
        default.items = ()
    for operation in Library(
        "geometry", records={"Options": RecordSchema("Options", (field,))}
    ).impls.values():
        restored = pickle.loads(pickle.dumps(operation))
        assert restored.schema == operation.schema
        assert restored.kind == operation.kind and restored.field == operation.field
        assert restored.schema.fields[0].has_default is True


@pytest.mark.parametrize("name", ["", "Point.bad", "_", "True", "None", "a-b", "int", "list"])
def test_invalid_schema_names(name):
    with pytest.raises(ValueError):
        RecordSchema(name, ())


@pytest.mark.parametrize("name", ["", "x.y", "_", "False", "a-b", "1x"])
def test_invalid_field_names(name):
    with pytest.raises(ValueError):
        RecordField(name)


@pytest.mark.parametrize(
    "type_text, default",
    [
        ("int", True),
        ("bool", 1),
        ("str", None),
        ("float", "1"),
        ("list[int]", [1, True]),
        ("dict[str, int]", {"x": "wrong"}),
        ("Point", {"x": 1}),
        ("Point?", {}),
        ("int | str", []),
        ("_", float("inf")),
        ("_", float("nan")),
        ("_", (1, 2)),
        ("_", {1: "bad key"}),
        ("_", object()),
    ],
)
def test_bad_default_types_and_nonportable_values(type_text, default):
    with pytest.raises(ValueError):
        RecordField("field", parse_type(type_text), True, default)


@pytest.mark.parametrize(
    "type_text",
    ["dict[int, str]", "dict[_, str]", "dict[str]", "list[int, str]", "Box[int]", "tuple[int]"],
)
def test_unsupported_generic_types_rejected(type_text):
    with pytest.raises(ValueError):
        RecordField("field", parse_type(type_text))


def test_required_versus_explicit_null_and_nullable_nominal_default():
    lib = NodeLibrary("geometry")
    schema = lib.record(
        "Label", [("required", "str?"), ("optional", "str?", None), ("point", "Point?", None)]
    )
    assert [(f.has_default, f.default) for f in schema.fields] == [
        (False, None),
        (True, None),
        (True, None),
    ]
    fields = library_to_json(lib)["records"][0]["fields"]
    assert "default" not in fields[0]
    assert fields[1]["default"] is None and fields[2]["default"] is None
    with pytest.raises(ValueError, match="has_default"):
        RecordField("x", ANY, False, 1)
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        RecordField("x", ANY, True, cyclic)


@pytest.mark.parametrize("node", ["Point", "Point.make", "Point.get.x", "Point.with.x"])
def test_generated_and_schema_host_collisions_are_atomic(node):
    lib = Library("geometry")
    sig = Signature(node, (), ())
    lib.add_signature(sig)
    with pytest.raises(ValueError):
        lib.add_record("Point", [RecordField("x")])
    assert lib.signatures == {node: sig} and lib.records == {}
    other = Library("geometry")
    other.add_record("Point", [RecordField("x")])
    with pytest.raises(ValueError):
        other.add_signature(sig)


def test_duplicate_schemas_fields_and_identity_are_rejected():
    lib = point_library()
    before = dict(lib.signatures)
    with pytest.raises(ValueError):
        lib.add_record("Point", [])
    assert lib.signatures == before
    with pytest.raises(ValueError, match="duplicate"):
        RecordSchema("Bad", (RecordField("x"), RecordField("x")))
    with pytest.raises(ValueError, match="identity"):
        Library("geometry").add_record(RecordSchema("Point", (), "other.Point"))


@pytest.mark.parametrize("type_text", ["Self", "Self?", "list[Self]", "dict[str, Self]"])
def test_local_recursive_schemas_rejected(type_text):
    lib = Library("geometry")
    with pytest.raises(ValueError, match="recursive"):
        lib.add_record("Self", [RecordField("value", parse_type(type_text))])
    assert lib.records == {} and lib.signatures == {} and lib.impls == {}


def test_forward_reference_cycle_rejected_when_closed():
    lib = NodeLibrary("geometry")
    lib.record("First", [("second", "Second")])
    before = dict(lib.signatures)
    with pytest.raises(ValueError, match="recursive"):
        lib.record("Second", [("first", "First?")])
    assert list(lib.records) == ["First"] and lib.signatures == before


def test_format_two_round_trip_preserves_order_defaults_effects_and_derived_impls(tmp_path):
    lib = point_library()
    lib.add_signature(Signature("host", (Port("x", default=None),), (), ("x",), True, "host docs"))
    lib.record("Empty", [])
    data = library_to_json(lib)
    assert data["kirsig"] == 2
    assert [r["name"] for r in data["records"]] == ["Point", "Empty"]
    assert [n["name"] for n in data["nodes"]] == ["host"]
    assert data["nodes"][0]["flags"] == {"mutates": ["x"], "ordered": True}
    restored = library_from_json(json.loads(json.dumps(data, allow_nan=False)))
    assert library_to_json(restored) == data
    assert restored.records == lib.records
    assert restored.signatures == lib.signatures
    assert "host" not in restored.impls
    assert all(isinstance(impl, RecordOperation) for impl in restored.impls.values())
    path = tmp_path / "geometry.kirsig.json"
    save_library(lib, path)
    assert library_to_json(load_library(path)) == data


def test_format_one_export_unchanged_without_records():
    lib = Library("legacy")
    lib.add_signature(Signature("host", (Port("value"),), (Port("out"),)))
    expected = {
        "kirsig": 1,
        "library": "legacy",
        "nodes": [{"name": "host", "inputs": [{"name": "value"}], "outputs": [{"name": "out"}]}],
    }
    assert library_to_json(lib) == expected
    assert library_to_json(library_from_json(expected)) == expected


def test_generated_signatures_cannot_be_independently_serialized_or_edited():
    data = library_to_json(point_library())
    data["nodes"].append({"name": "Point.make", "inputs": [], "outputs": []})
    with pytest.raises(KirSignatureError):
        library_from_json(data)
    lib = point_library()
    lib.signatures["Point.make"] = replace(lib.signatures["Point.make"], ordered=True)
    with pytest.raises(KirSignatureError, match="modified"):
        library_to_json(lib)


@pytest.mark.parametrize(
    "records",
    [
        [{"name": "Bad", "fields": [{"name": "x", "type": "int", "default": None}]}],
        [{"name": "Bad", "fields": [{"name": "x", "type": "list["}]}],
        [{"name": "Bad"}],
        [{"name": "A", "fields": []}, {"name": "A", "fields": []}],
        [{"name": "A", "fields": [{"name": "a", "type": "A?"}]}],
    ],
)
def test_bad_format_two_schemas_raise_signature_errors(records):
    with pytest.raises(KirSignatureError):
        library_from_json({"kirsig": 2, "library": "geometry", "records": records, "nodes": []})


@pytest.mark.parametrize("register_first", [False, True])
def test_handwritten_ports_qualify_only_known_local_records(register_first):
    lib = Library("geometry")
    signature = Signature(
        "host",
        (Port("point", parse_type("list[Point?]")), Port("foreign", parse_type("Image"))),
        (Port("point", parse_type("Point | other.Point")),),
        ("point",),
        True,
        "host docs",
    )
    if register_first:
        lib.add_record("Point", [])
    lib.add_signature(signature)
    if not register_first:
        lib.add_record("Point", [])
    result = lib.signatures["host"]
    assert result.inputs[0].type == parse_type("list[geometry.Point?]")
    assert result.inputs[1].type == parse_type("Image")
    assert result.outputs[0].type == parse_type("geometry.Point | other.Point")
    assert (result.mutates, result.ordered, result.doc) == (("point",), True, "host docs")
    assert library_from_json(library_to_json(lib)).signatures == lib.signatures


def test_generated_names_do_not_confuse_field_and_operation_names():
    lib = NodeLibrary("geometry")
    fields = ["get", "with", "make", "self", "record", "value", "schema"]
    lib.record("Names", [(name, "int") for name in fields])
    assert len(lib.signatures) == 1 + 2 * len(fields)
    assert all(f"Names.get.{name}" in lib for name in fields)
    assert all(f"Names.with.{name}" in lib for name in fields)
    values = {name: index for index, name in enumerate(fields)}
    record = lib.impls["Names.make"](**values)
    assert all(
        lib.impls[f"Names.get.{name}"](record=record) == value for name, value in values.items()
    )


def test_any_record_field_type_is_explicit_and_empty_v2_exports_v1():
    lib = Library("geometry")
    lib.add_record("AnyField", [RecordField("value")])
    assert library_to_json(lib)["records"][0]["fields"] == [{"name": "value", "type": "_"}]
    empty = library_from_json({"kirsig": 2, "library": "empty", "nodes": [], "records": []})
    assert library_to_json(empty) == {"kirsig": 1, "library": "empty", "nodes": []}


@pytest.mark.parametrize(
    "type_",
    [
        TypeExpr("optional", "", (ANY,)),
        TypeExpr("optional", "", (parse_type("int | str"),)),
        TypeExpr("optional", "", (parse_type("int?"),)),
        TypeExpr("union", "", (parse_type("int | str"), parse_type("float"))),
    ],
)
def test_programmatic_types_normalize_to_lossless_signature_spelling(type_):
    lib = Library("geometry")
    lib.add_record("Normalized", [RecordField("value", type_)])
    restored = library_from_json(library_to_json(lib))
    assert restored.records == lib.records
    assert restored.signatures == lib.signatures


@pytest.mark.parametrize(
    "type_", [TypeExpr("any", []), TypeExpr([], ""), TypeExpr("name", "int", [])]
)
def test_mutable_type_components_cannot_enter_frozen_schemas(type_):
    with pytest.raises(ValueError, match="immutable"):
        RecordField("value", type_)


@pytest.mark.parametrize("type_value", [None, ["int"], 1, {"type": "int"}])
def test_format_two_requires_explicit_string_field_type(type_value):
    data = {
        "kirsig": 2,
        "library": "geometry",
        "nodes": [],
        "records": [{"name": "Bad", "fields": [{"name": "value", "type": type_value}]}],
    }
    with pytest.raises(KirSignatureError, match="explicit string"):
        library_from_json(data)
    del data["records"][0]["fields"][0]["type"]
    with pytest.raises(KirSignatureError, match="explicit string"):
        library_from_json(data)


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_schema_defaults_reject_reinitialization_and_pickle_state_mutation(protocol):
    lib = NodeLibrary("geometry")
    schema = lib.record("Options", [("values", "dict[str, list[int]]", {"x": [1]})])
    record = lib.impls["Options.make"]()
    member = schema.fields[0]
    mapping = member.default
    sequence = mapping.items[0][1]
    attempts = [
        (schema, ("Changed", (), "geometry.Changed")),
        (member, ("changed", ANY, True, "changed")),
        (mapping, ((("x", [2]),),)),
        (sequence, ((2,),)),
    ]
    for original, args in attempts:
        restored = pickle.loads(pickle.dumps(original, protocol=protocol))
        assert restored == original
        for value in (original, restored):
            assert not hasattr(value, "__dict__")
            before = pickle.dumps(value, protocol=protocol)
            with pytest.raises(FrozenInstanceError, match="reinitialize"):
                value.__init__(*args)
            with pytest.raises(FrozenInstanceError, match="state"):
                value.__setstate__({"name": "changed", "items": ()})
            assert pickle.dumps(value, protocol=protocol) == before
    assert lib.impls["Options.get.values"](record) == {"x": [1]}
    assert lib.impls["Options.get.values"](lib.impls["Options.make"]()) == {"x": [1]}
    assert replace(member, name="other").name == "other"
    assert replace(schema, name="Other", schema_id="geometry.Other").fields == schema.fields


@pytest.mark.parametrize("replacement", [True, 1.0])
def test_export_rejects_type_coercing_generated_default_edits(replacement):
    lib = NodeLibrary("geometry")
    lib.record("R", [("x", "list[int]", [1])])
    lib.signatures["R.make"].inputs[0].default[0] = replacement
    with pytest.raises(KirSignatureError, match="modified"):
        library_to_json(lib)
    assert thaw_default(lib.records["R"].fields[0].default) == [1]


@pytest.mark.parametrize(
    "left,right", [(True, 1), (1, 1.0), ([True], [1]), ({"x": [1]}, {"x": [True]})]
)
def test_schema_compatibility_distinguishes_portable_scalar_types(left, right):
    a = RecordSchema("R", (RecordField("x", ANY, True, left),), "geometry.R")
    b = RecordSchema("R", (RecordField("x", ANY, True, right),), "geometry.R")
    assert not portable_default_equal(left, right)
    assert not record_schema_equal(a, b)
    assert record_schema_equal(a, pickle.loads(pickle.dumps(a)))


def test_nested_schema_type_cannot_be_reinitialized_and_keeps_ast_contract():
    schema = Library("geometry").add_record("R", [RecordField("x", parse_type("list[int]"))])
    type_ = schema.fields[0].type
    original = asdict(type_)
    assert original == {
        "kind": "generic",
        "name": "list",
        "args": ({"kind": "name", "name": "int", "args": ()},),
    }
    for value in (type_, type_.args[0], copy.deepcopy(type_), pickle.loads(pickle.dumps(type_))):
        before = asdict(value)
        with pytest.raises(FrozenInstanceError, match="reinitialize"):
            value.__init__("any")
        with pytest.raises(FrozenInstanceError, match="state"):
            value.__setstate__({"kind": "any", "name": "", "args": ()})
        assert asdict(value) == before
    assert copy.deepcopy(type_) == type_ == pickle.loads(pickle.dumps(type_))
    assert hash(type_) == hash(copy.deepcopy(type_))
    assert asdict(schema.fields[0].type) == original


def test_records_cannot_be_smuggled_into_format_one():
    with pytest.raises(KirSignatureError, match="format 2"):
        library_from_json(
            {
                "kirsig": 1,
                "library": "geometry",
                "records": [{"name": "Point", "fields": []}],
                "nodes": [],
            }
        )
