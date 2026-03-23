import pytest

from kohakunode.engine.registry import FunctionSpec, Registry
from kohakunode.errors import KirRuntimeError


def _add(a, b):
    return a + b


def _greet(name, greeting="hello"):
    return f"{greeting}, {name}"


# ---------------------------------------------------------------------------
# test_register_and_lookup
# ---------------------------------------------------------------------------


def test_register_and_lookup():
    registry = Registry()
    spec = registry.register("add", _add, output_names=["result"])

    assert isinstance(spec, FunctionSpec)
    assert spec.name == "add"
    assert spec.func is _add

    looked_up = registry.lookup("add")
    assert looked_up is spec


# ---------------------------------------------------------------------------
# test_register_duplicate
# ---------------------------------------------------------------------------


def test_register_duplicate():
    registry = Registry()
    registry.register("add", _add, output_names=["result"])

    with pytest.raises(KirRuntimeError, match="already registered"):
        registry.register("add", _add, output_names=["result"])


# ---------------------------------------------------------------------------
# test_lookup_missing
# ---------------------------------------------------------------------------


def test_lookup_missing():
    registry = Registry()

    with pytest.raises(KirRuntimeError, match="not registered"):
        registry.lookup("nonexistent")


# ---------------------------------------------------------------------------
# test_auto_introspect
# ---------------------------------------------------------------------------


def test_auto_introspect():
    registry = Registry()
    spec = registry.register("greet", _greet, output_names=["msg"])

    assert spec.input_names == ["name", "greeting"]
    assert spec.defaults == {"greeting": "hello"}


def test_auto_introspect_no_defaults():
    registry = Registry()
    spec = registry.register("add", _add, output_names=["result"])

    assert spec.input_names == ["a", "b"]
    assert spec.defaults == {}


# ---------------------------------------------------------------------------
# test_unregister
# ---------------------------------------------------------------------------


def test_unregister():
    registry = Registry()
    registry.register("add", _add, output_names=["result"])

    assert registry.has("add")
    registry.unregister("add")
    assert not registry.has("add")


def test_unregister_missing_raises():
    registry = Registry()

    with pytest.raises(KirRuntimeError, match="not registered"):
        registry.unregister("nonexistent")


# ---------------------------------------------------------------------------
# test_list_functions
# ---------------------------------------------------------------------------


def test_list_functions():
    registry = Registry()
    registry.register("zebra", lambda: None, output_names=[])
    registry.register("apple", lambda: None, output_names=[])
    registry.register("mango", lambda: None, output_names=[])

    names = registry.list_functions()
    assert names == ["apple", "mango", "zebra"]


def test_list_functions_empty():
    registry = Registry()
    assert registry.list_functions() == []


# ---------------------------------------------------------------------------
# test_register_decorator
# ---------------------------------------------------------------------------


def test_register_decorator():
    registry = Registry()

    @registry.register_decorator(name="multiply", output_names=["result"])
    def multiply(a, b):
        return a * b

    assert registry.has("multiply")
    spec = registry.lookup("multiply")
    assert spec.name == "multiply"
    assert spec.func is multiply
    assert spec.output_names == ["result"]


def test_register_decorator_uses_func_name_when_no_name_given():
    registry = Registry()

    @registry.register_decorator(output_names=["result"])
    def subtract(a, b):
        return a - b

    assert registry.has("subtract")


# ---------------------------------------------------------------------------
# test_has
# ---------------------------------------------------------------------------


def test_has_returns_true_when_registered():
    registry = Registry()
    registry.register("add", _add, output_names=["result"])
    assert registry.has("add") is True


def test_has_returns_false_when_not_registered():
    registry = Registry()
    assert registry.has("add") is False


def test_has_false_after_unregister():
    registry = Registry()
    registry.register("add", _add, output_names=["result"])
    registry.unregister("add")
    assert registry.has("add") is False
