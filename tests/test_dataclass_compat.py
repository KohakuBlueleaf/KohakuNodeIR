"""Explicit pickle state hooks survive frozen/slots on all supported Pythons."""

import copy
import pickle
from dataclasses import FrozenInstanceError

import pytest

from kohakunode._dataclass import stateful_dataclass
from kohakunode.events import Event
from kohakunode.records import construct
from kohakunode.sig.records import FrozenDict, FrozenList, RecordField, RecordSchema
from kohakunode.syntax.ast import ANY, TypeExpr


def test_explicit_state_hooks_are_restored_without_replacing_other_methods():
    class Example:
        value: int

        def __getstate__(self):
            return {"value": self.value}

        def __setstate__(self, state):
            raise TypeError("explicit state rejection")

        def __reduce__(self):
            return (int, (self.value,))

    getstate = Example.__getstate__
    setstate = Example.__setstate__
    reduce = Example.__reduce__
    decorated = stateful_dataclass(frozen=True, slots=True)(Example)
    assert decorated.__getstate__ is getstate
    assert decorated.__setstate__ is setstate
    assert decorated.__reduce__ is reduce
    instance = decorated(7)
    assert instance.__getstate__() == {"value": 7}
    with pytest.raises(TypeError, match="explicit state rejection"):
        instance.__setstate__({"value": 8})
    with pytest.raises(FrozenInstanceError):
        instance.value = 8
    assert instance.value == 7


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_validated_pickle_roundtrips_and_rejected_state_preserve_nested_values(protocol):
    schema = RecordSchema("Example", (RecordField("data", ANY),), "test.Example")
    value = construct(schema, data={"values": [1, True, 2.0]})
    outer = construct(schema, data=value)
    event = Event.capture("example", {"record": value})
    field = RecordField("default", ANY, True, {"values": [1]})
    specimens = [
        value,
        event,
        schema,
        field,
        FrozenList((1,)),
        FrozenDict((("x", 1),)),
        TypeExpr("generic", "list", (TypeExpr("name", "int"),)),
    ]
    digest = outer.__togeari_digest__()
    for original in specimens:
        restored = pickle.loads(pickle.dumps(original, protocol=protocol))
        assert restored == original == copy.deepcopy(original)
        for instance in (original, restored):
            before = pickle.dumps(instance, protocol=protocol)
            with pytest.raises((FrozenInstanceError, TypeError)):
                instance.__setstate__(["corrupt", (), None])
            assert pickle.dumps(instance, protocol=protocol) == before
            assert hash(instance) == hash(original)
    assert outer.__togeari_digest__() == digest
    assert value["data"] == {"values": [1, True, 2.0]}
    assert event.decode({schema.schema_id: schema}) == {"record": value}
