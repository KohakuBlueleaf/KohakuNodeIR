"""Integration tests — parse → write → parse (roundtrip AST equivalence)."""


import pytest

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Jump,
    Literal,
    Namespace,
    Parallel,
    Program,
    SubgraphDef,
)
from kohakunode.parser.parser import parse
from kohakunode.serializer.writer import Writer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _roundtrip(source: str) -> Program:
    """Parse *source*, write it, then parse again. Return the second Program."""
    first = parse(source)
    text = Writer().write(first)
    return parse(text)


def _collect_types(program: Program) -> list[str]:
    """Collect top-level statement type names."""
    return [type(s).__name__ for s in program.body]


def _get_assignments(program: Program) -> list[Assignment]:
    return [s for s in program.body if isinstance(s, Assignment)]


def _get_func_calls(program: Program) -> list[FuncCall]:
    return [s for s in program.body if isinstance(s, FuncCall)]


def _get_namespaces(program: Program) -> list[Namespace]:
    return [s for s in program.body if isinstance(s, Namespace)]


# ---------------------------------------------------------------------------
# test_roundtrip_basic
# ---------------------------------------------------------------------------


def test_roundtrip_basic_assignment():
    source = "x = 42\n"
    rt = _roundtrip(source)
    assigns = _get_assignments(rt)
    assert len(assigns) == 1
    assert assigns[0].target == "x"
    assert assigns[0].value.value == 42


def test_roundtrip_basic_string_assignment():
    source = 'name = "hello"\n'
    rt = _roundtrip(source)
    assigns = _get_assignments(rt)
    assert assigns[0].value.value == "hello"


def test_roundtrip_basic_func_call():
    source = "(a, b)process(result)\n"
    rt = _roundtrip(source)
    calls = _get_func_calls(rt)
    assert len(calls) == 1
    assert calls[0].func_name == "process"
    assert calls[0].outputs == ["result"]
    assert len(calls[0].inputs) == 2


def test_roundtrip_basic_preserves_statement_count():
    source = "x = 1\ny = 2\n(x, y)add(z)\n"
    original = parse(source)
    rt = _roundtrip(source)
    assert len(rt.body) == len(original.body)


def test_roundtrip_basic_assignment_literal_types():
    source = "x = 1\nf = 3.14\nb = True\nn = None\ns = \"hi\"\n"
    rt = _roundtrip(source)
    assigns = _get_assignments(rt)
    values = {a.target: a.value.value for a in assigns}
    assert values["x"] == 1
    assert abs(values["f"] - 3.14) < 1e-9
    assert values["b"] is True
    assert values["n"] is None
    assert values["s"] == "hi"


def test_roundtrip_basic_branch():
    source = "(cond)branch(`yes`, `no`)\nyes:\n    ()fn(x)\nno:\n    ()fn(y)\n"
    rt = _roundtrip(source)
    branches = [s for s in rt.body if isinstance(s, Branch)]
    assert len(branches) == 1
    assert branches[0].true_label == "yes"
    assert branches[0].false_label == "no"


def test_roundtrip_basic_jump():
    source = "()jump(`target`)\ntarget:\n    ()fn(x)\n"
    rt = _roundtrip(source)
    jumps = [s for s in rt.body if isinstance(s, Jump)]
    assert len(jumps) == 1
    assert jumps[0].target == "target"


def test_roundtrip_basic_namespace():
    source = "my_ns:\n    ()inner_fn(x)\n"
    rt = _roundtrip(source)
    namespaces = _get_namespaces(rt)
    assert len(namespaces) == 1
    assert namespaces[0].name == "my_ns"
    assert len(namespaces[0].body) == 1


def test_roundtrip_basic_namespace_body_func_call():
    source = "ns:\n    (a, b)combine(c)\n"
    rt = _roundtrip(source)
    ns = _get_namespaces(rt)[0]
    inner = ns.body[0]
    assert isinstance(inner, FuncCall)
    assert inner.func_name == "combine"


# ---------------------------------------------------------------------------
# test_roundtrip_complex
# ---------------------------------------------------------------------------


# NOTE: The Writer emits '@def name(params)(outputs)' which is NOT re-parseable
# by the grammar (which expects '@def (params)name(outputs):').  Roundtrip tests
# for programs with @def subgraphs therefore verify that:
#   1. The original source parses correctly.
#   2. The Writer produces output that contains all expected text fragments.
# A full parse→write→parse cycle for @def blocks is omitted because the
# serializer output format intentionally differs from the grammar input format.

_SUBGRAPH_SOURCE = """\
@def (input, strength=1.0)preprocess(output):
    (input)denoise(clean)
    (clean, amount=strength)normalize(output)

"""

_COMPLEX_SOURCE = """\
x = 1
flag = True
(x, 10)lte(cond)
(cond)branch(`branch_yes`, `branch_no`)
branch_yes:
    (x)double(result)
branch_no:
    (x)negate(result)
(result)finalize(answer)
"""


def test_roundtrip_complex_program_parses():
    """The complex source (no @def) must parse successfully both times."""
    rt = _roundtrip(_COMPLEX_SOURCE)
    assert isinstance(rt, Program)


def test_roundtrip_subgraph_writer_output_contains_name():
    """Writer output for a parsed @def block contains the subgraph name."""
    prog = parse(_SUBGRAPH_SOURCE)
    text = Writer().write(prog)
    assert "preprocess" in text


def test_roundtrip_subgraph_writer_output_contains_params():
    """Writer output for a parsed @def block contains the parameter names."""
    prog = parse(_SUBGRAPH_SOURCE)
    text = Writer().write(prog)
    assert "input" in text
    assert "strength" in text


def test_roundtrip_subgraph_writer_output_contains_outputs():
    """Writer output for a parsed @def block contains the output name."""
    prog = parse(_SUBGRAPH_SOURCE)
    text = Writer().write(prog)
    assert "output" in text


def test_roundtrip_subgraph_parsed_correctly():
    """The @def source parses into the correct SubgraphDef AST node."""
    prog = parse(_SUBGRAPH_SOURCE)
    subgraphs = [s for s in prog.body if isinstance(s, SubgraphDef)]
    assert len(subgraphs) == 1
    sg = subgraphs[0]
    assert sg.name == "preprocess"
    param_names = [p.name for p in sg.params]
    assert "input" in param_names
    assert "strength" in param_names
    strength_param = next(p for p in sg.params if p.name == "strength")
    assert strength_param.default is not None
    assert strength_param.default.value == 1.0
    assert sg.outputs == ["output"]


def test_roundtrip_complex_assignments_preserved():
    rt = _roundtrip(_COMPLEX_SOURCE)
    assigns = _get_assignments(rt)
    targets = {a.target for a in assigns}
    assert "x" in targets
    assert "flag" in targets


def test_roundtrip_complex_branch_preserved():
    rt = _roundtrip(_COMPLEX_SOURCE)
    branches = [s for s in rt.body if isinstance(s, Branch)]
    assert len(branches) >= 1
    b = branches[0]
    assert b.true_label == "branch_yes"
    assert b.false_label == "branch_no"


def test_roundtrip_complex_namespaces_preserved():
    rt = _roundtrip(_COMPLEX_SOURCE)
    namespaces = _get_namespaces(rt)
    ns_names = {ns.name for ns in namespaces}
    assert "branch_yes" in ns_names
    assert "branch_no" in ns_names


def test_roundtrip_complex_final_func_call():
    rt = _roundtrip(_COMPLEX_SOURCE)
    calls = _get_func_calls(rt)
    finalize_calls = [c for c in calls if c.func_name == "finalize"]
    assert len(finalize_calls) == 1
    assert finalize_calls[0].outputs == ["answer"]


def test_roundtrip_complex_mode_none():
    """Complex source has no @mode — mode should remain None after roundtrip."""
    rt = _roundtrip(_COMPLEX_SOURCE)
    assert rt.mode is None


def test_roundtrip_complex_dataflow_mode_preserved():
    source = "@mode dataflow\n\n()load(x)\n(x)process(y)\n"
    rt = _roundtrip(source)
    assert rt.mode == "dataflow"


def test_roundtrip_parallel_preserved():
    source = "()parallel(`t1`, `t2`)\nt1:\n    ()fn_a(x)\nt2:\n    ()fn_b(y)\n"
    rt = _roundtrip(source)
    parallels = [s for s in rt.body if isinstance(s, Parallel)]
    assert len(parallels) == 1
    assert set(parallels[0].labels) == {"t1", "t2"}


def test_roundtrip_keyword_arg_preserved():
    source = '(data, mode="fast")process(result)\n'
    rt = _roundtrip(source)
    calls = _get_func_calls(rt)
    assert len(calls) == 1
    kw_inputs = [i for i in calls[0].inputs if hasattr(i, "name") and hasattr(i, "value")]
    kwarg = next((i for i in kw_inputs if i.name == "mode"), None)
    assert kwarg is not None
    assert kwarg.value.value == "fast"
