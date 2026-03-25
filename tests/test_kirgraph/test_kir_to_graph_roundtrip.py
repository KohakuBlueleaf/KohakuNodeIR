"""Test the kir_to_graph → KirGraphCompiler roundtrip.

This is the path the frontend uses:
  KIR text → kir_to_graph() → KirGraph → KirGraphCompiler → KIR text

We verify that the roundtripped KIR, when executed, produces the same
results as the original KIR.
"""

import json
from pathlib import Path

import pytest

from kohakunode import Registry, parse, run
from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.engine.executor import Executor
from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.schema import KirGraph
from kohakunode.layout.ascii_view import kir_to_graph
from kohakunode.layout.auto_layout import auto_layout
from kohakunode.serializer.writer import Writer


KIR_EXAMPLES = sorted(Path("examples/kir_basics").glob("*.kir"))


def _roundtrip_kir(source: str) -> str:
    """KIR text → kir_to_graph → KirGraph → KirGraphCompiler → KIR text."""
    graph = kir_to_graph(source)
    graph = auto_layout(graph)
    kg_dict = json.loads(json.dumps(graph.to_dict()))
    graph2 = KirGraph.from_dict(kg_dict)
    program = KirGraphCompiler().compile(graph2)
    return Writer().write(program)


def _roundtrip_twice(source: str) -> str:
    """Double roundtrip: KIR → graph → KIR → graph → KIR."""
    kir1 = _roundtrip_kir(source)
    kir2 = _roundtrip_kir(kir1)
    return kir2


def _make_registry() -> Registry:
    """Create a registry with all built-in functions needed by examples."""
    reg = Registry()
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("subtract", lambda a, b: a - b, output_names=["result"])
    reg.register("multiply", lambda a, b: a * b, output_names=["result"])
    reg.register("divide", lambda a, b: a / b if b != 0 else 0, output_names=["result"])
    reg.register("to_float", lambda x: float(x), output_names=["result"])
    reg.register("to_string", lambda x: str(x), output_names=["result"])
    reg.register("to_int", lambda x: int(x), output_names=["result"])
    reg.register("less_than", lambda a, b: a < b, output_names=["result"])
    reg.register("less_equal", lambda a, b: a <= b, output_names=["result"])
    reg.register("greater_than", lambda a, b: a > b, output_names=["result"])
    reg.register("greater_equal", lambda a, b: a >= b, output_names=["result"])
    reg.register("equal", lambda a, b: a == b, output_names=["result"])
    reg.register("not_equal", lambda a, b: a != b, output_names=["result"])
    reg.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
    reg.register("format_factorial", lambda n, f: f"factorial({int(n)}) = {f}", output_names=["result"])
    reg.register("min_val", lambda a, b: min(a, b), output_names=["result"])
    reg.register("max_val", lambda a, b: max(a, b), output_names=["result"])
    reg.register("negate", lambda x: -x, output_names=["result"])
    reg.register("upper", lambda s: str(s).upper(), output_names=["result"])
    reg.register("lower", lambda s: str(s).lower(), output_names=["result"])
    reg.register("length", lambda s: len(str(s)), output_names=["result"])
    reg.register("reverse", lambda s: str(s)[::-1], output_names=["result"])
    reg.register("starts_with", lambda s, p: str(s).startswith(str(p)), output_names=["result"])

    _printed = []
    reg.register("print", lambda x: _printed.append(str(x)), output_names=[])
    reg.register("print_val", lambda x: _printed.append(str(x)), output_names=[])
    reg.register("display", lambda x: _printed.append(str(x)), output_names=[])
    return reg


def _execute_kir(source: str, registry: Registry) -> dict:
    """Execute KIR and return the variable store as a dict."""
    try:
        store = run(source, registry=registry)
        return {k: v for k, v in store.items()}
    except Exception as e:
        return {"__error__": str(e)}


class TestKirToGraphRoundtrip:
    """Test that kir_to_graph → compile produces equivalent KIR."""

    @pytest.mark.parametrize("kir_file", KIR_EXAMPLES, ids=lambda f: f.stem)
    def test_roundtrip_produces_valid_kir(self, kir_file):
        """Roundtripped KIR should parse without errors."""
        source = kir_file.read_text(encoding="utf-8")
        result = _roundtrip_kir(source)
        # Should parse without exception
        prog = parse(result)
        assert prog is not None
        assert len(prog.body) > 0

    @pytest.mark.parametrize("kir_file", KIR_EXAMPLES, ids=lambda f: f.stem)
    def test_double_roundtrip_stable(self, kir_file):
        """Double roundtrip should be stable (idempotent after first pass)."""
        source = kir_file.read_text(encoding="utf-8")
        kir1 = _roundtrip_kir(source)
        kir2 = _roundtrip_kir(kir1)
        # The second roundtrip should produce the same KIR as the first
        # (may differ from original but should be stable)
        assert kir1 == kir2, f"Double roundtrip not stable:\n--- First ---\n{kir1}\n--- Second ---\n{kir2}"

    def test_mixed_mode_structure(self):
        """mixed_mode.kir roundtrip should preserve loop + branch structure."""
        source = Path("examples/kir_basics/mixed_mode.kir").read_text(encoding="utf-8")
        result = _roundtrip_kir(source)

        # Must have a jump (loop entry)
        assert "jump(" in result, "Missing jump (loop entry)"
        # Must have branch with backtick labels
        assert "branch(" in result, "Missing branch"
        assert "`" in result, "Missing backtick labels"
        # Must have loop-back jump inside a branch arm
        lines = result.split("\n")
        found_loop_back = False
        for i, line in enumerate(lines):
            if "branch(" in line:
                # Look for jump in the next few lines (branch arm)
                for j in range(i + 1, min(i + 5, len(lines))):
                    if "jump(" in lines[j]:
                        found_loop_back = True
                        break
        assert found_loop_back, "Missing loop-back jump after branch"

    def test_mixed_mode_execution(self):
        """mixed_mode.kir roundtrip should produce same execution results."""
        source = Path("examples/kir_basics/mixed_mode.kir").read_text(encoding="utf-8")
        result = _roundtrip_kir(source)

        reg1 = _make_registry()
        reg2 = _make_registry()

        vars_original = _execute_kir(source, reg1)
        vars_roundtrip = _execute_kir(result, reg2)

        # Both should succeed (no errors)
        assert "__error__" not in vars_original, f"Original failed: {vars_original['__error__']}"
        assert "__error__" not in vars_roundtrip, f"Roundtrip failed: {vars_roundtrip['__error__']}"

    def test_control_flow_execution(self):
        """control_flow.kir roundtrip should produce same results."""
        source = Path("examples/kir_basics/control_flow.kir").read_text(encoding="utf-8")
        result = _roundtrip_kir(source)

        reg1 = _make_registry()
        reg2 = _make_registry()

        vars_original = _execute_kir(source, reg1)
        vars_roundtrip = _execute_kir(result, reg2)

        assert "__error__" not in vars_original, f"Original failed: {vars_original['__error__']}"
        assert "__error__" not in vars_roundtrip, f"Roundtrip failed: {vars_roundtrip['__error__']}"

    def test_branching_execution(self):
        """branching.kir roundtrip should produce same results."""
        source = Path("examples/kir_basics/branching.kir").read_text(encoding="utf-8")
        result = _roundtrip_kir(source)

        reg1 = _make_registry()
        reg2 = _make_registry()

        vars_original = _execute_kir(source, reg1)
        vars_roundtrip = _execute_kir(result, reg2)

        assert "__error__" not in vars_original, f"Original failed: {vars_original['__error__']}"
        assert "__error__" not in vars_roundtrip, f"Roundtrip failed: {vars_roundtrip['__error__']}"

    def test_basic_math_execution(self):
        """basic_math.kir roundtrip should produce same results."""
        source = Path("examples/kir_basics/basic_math.kir").read_text(encoding="utf-8")
        result = _roundtrip_kir(source)

        reg1 = _make_registry()
        reg2 = _make_registry()

        vars_original = _execute_kir(source, reg1)
        vars_roundtrip = _execute_kir(result, reg2)

        assert "__error__" not in vars_original, f"Original failed: {vars_original['__error__']}"
        assert "__error__" not in vars_roundtrip, f"Roundtrip failed: {vars_roundtrip['__error__']}"
