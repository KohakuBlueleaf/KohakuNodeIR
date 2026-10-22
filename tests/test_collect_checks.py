"""Collection reads occur at body end and unsafe aliases/control are explicit errors."""

import pytest

from kohakunode import KirCheckError, NodeLibrary, compile_source


def checked(source, libraries=None):
    return compile_source(source, libraries, passes=[])


def test_result_read_occurs_after_body_and_target_exists_after_empty_input():
    checked("([])collect(x, `body`, value -> result)\nbody:\n    value = 1\n(result)len(n)\n")


def test_preexisting_target_can_supply_input_before_publication():
    checked("result = [1, 2]\n(result)collect(x, `body`, x -> result)\nbody:\n    seen = x\n")


def test_result_can_be_carried_from_before_collection():
    checked("value = 4\n([1, 2])collect(x, `body`, value -> result)\nbody:\n    seen = x\n")


def test_result_must_be_defined_on_every_body_completion_path():
    with pytest.raises(KirCheckError, match="E020"):
        checked("([1])collect(x, `body`, missing -> result)\nbody:\n    seen = x\n")
    with pytest.raises(KirCheckError, match="E020"):
        checked("""([1])collect(x, `body`, value -> result)
body:
    (True)branch(`yes`, `no`)
    yes:
        value = x
    no:
        skipped = x
""")


@pytest.mark.parametrize(
    "source",
    [
        "([1])collect(result, `body`, 1 -> result)\nbody:\n    y = 1\n",
        "result = 0\n([1])collect(x, `body`, result -> result)\nbody:\n    y = x\n",
        "([1])collect(x, `body`, x -> result)\nbody:\n    result = 1\n",
        "result = 0\n([1])collect(x, `body`, x -> result)\nbody:\n    (result)len(y)\n",
    ],
)
def test_target_is_not_available_inside_its_own_body(source):
    with pytest.raises(KirCheckError, match="E070"):
        checked(source)


def test_escaping_jump_is_rejected_but_nested_internal_loop_is_allowed():
    with pytest.raises(KirCheckError, match="E071"):
        checked(
            "([1])collect(x, `body`, x -> result)\nbody:\n    ()jump(`out`)\nout:\n    done = 1\n"
        )
    checked("""([1])collect(x, `body`, value -> result)
body:
    ()jump(`inner`)
    inner:
        value = x
""")


def test_mutation_rejected_even_in_caller_or_unused_definition():
    library = NodeLibrary("effects")

    @library.node(mutates=["items"], outputs=["items"])
    def mutate(items: list) -> list:
        items.append(1)
        return items

    collection = "([1])collect(x, `body`, x -> result)\nbody:\n    seen = x\n"
    for prefix in (
        "([])mutate(xs)\n",
        "@def (items: list)unused(out: list):\n    (items)mutate(out)\n",
    ):
        with pytest.raises(KirCheckError, match="E072"):
            checked(prefix + collection, [library])
    # Existing iteration programs keep their existing mutation contract.
    checked("xs = []\n([1])each(x, `body`)\nbody:\n    (xs)mutate(xs)\n", [library])


@pytest.mark.parametrize("forward_body", [False, True])
def test_collection_type_dependencies_are_not_lexical_order_dependent(forward_body):
    body = "first:\n    seen = 0\n"
    first = "([1])collect(_, `first`, 7 -> xs)\n"
    source = (
        (body + first if forward_body else first + body) + """([1])collect(_, `second`, xs -> ys)
second:
    seen = 1
@def (value: list[list[str]])consume(out):
    out = value
(ys)consume(result)
"""
    )
    with pytest.raises(KirCheckError, match="list\\[list\\[int\\]\\]"):
        checked(source)


def test_collection_type_is_list_of_known_yield_type():
    with pytest.raises(KirCheckError, match="E040"):
        checked("""@def (x: int)consume(y):
    y = x
([1])collect(x, `body`, value -> result)
body:
    value = 3
(result)consume(y)
""")
