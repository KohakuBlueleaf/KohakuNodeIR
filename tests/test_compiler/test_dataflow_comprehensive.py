"""Comprehensive tests for @dataflow: block semantics.

Tests cover all interaction patterns between scoped @dataflow: blocks
and control flow constructs (loops, branches, namespaces).
"""

import pytest

from kohakunode import Executor, Registry, parse
from kohakunode.ast.nodes import (
    Assignment,
    DataflowBlock,
    FuncCall,
    Jump,
    Namespace,
)
from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.serializer.writer import Writer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_registry():
    """Create a registry with basic math/utility functions."""
    reg = Registry()
    reg.register("add", lambda a, b: a + b, output_names=["result"])
    reg.register("subtract", lambda a, b: a - b, output_names=["result"])
    reg.register("multiply", lambda a, b: a * b, output_names=["result"])
    reg.register("divide", lambda a, b: a / b if b != 0 else 0, output_names=["result"])
    reg.register("less_than", lambda a, b: a < b, output_names=["result"])
    reg.register("greater_than", lambda a, b: a > b, output_names=["result"])
    reg.register("equal", lambda a, b: a == b, output_names=["result"])
    reg.register("to_int", lambda v: int(v), output_names=["result"])
    reg.register("to_float", lambda v: float(v), output_names=["result"])
    reg.register("to_string", lambda v: str(v), output_names=["result"])
    reg.register("concat", lambda a, b: str(a) + str(b), output_names=["result"])
    reg.register("negate", lambda v: -v, output_names=["result"])
    reg.register("identity", lambda v: v, output_names=["result"])
    reg.register("print", lambda v: None, output_names=[])
    return reg


def run_kir(source, validate=False):
    """Parse, compile, and execute a KIR source string."""
    reg = make_registry()
    exe = Executor(registry=reg, validate=validate)
    return exe.execute_source(source)


def compile_kir(source):
    """Parse and compile (but don't execute) — return compiled Program."""
    prog = parse(source)
    compiler = DataflowCompiler()
    return compiler.transform(prog)


def compile_and_show(source):
    """Parse, compile, and return (before, after) KIR text."""
    prog = parse(source)
    writer = Writer()
    before = writer.write(prog)
    compiler = DataflowCompiler()
    compiled = compiler.transform(prog)
    after = writer.write(compiled)
    return before, after


# ===========================================================================
# 1. Basic scoped dataflow
# ===========================================================================


class TestBasicDataflow:
    def test_single_block_reorders(self):
        """Statements in @dataflow: get topologically sorted."""
        source = """\
@dataflow:
    (x, y)add(z)
    ()identity(y)
    ()identity(x)
"""
        compiled = compile_kir(source)
        # DataflowBlock should be gone
        assert not any(isinstance(s, DataflowBlock) for s in compiled.body)
        # identity(x) and identity(y) should come before add(z)
        names = [s.func_name for s in compiled.body if isinstance(s, FuncCall)]
        add_idx = names.index("add")
        id_indices = [i for i, n in enumerate(names) if n == "identity"]
        for idx in id_indices:
            assert idx < add_idx

    def test_single_block_executes(self):
        """@dataflow: block executes correctly after compilation."""
        store = run_kir("""\
x = 10
y = 20
@dataflow:
    (x, y)add(sum)
    (x, y)multiply(product)
""")
        assert store.get("sum") == 30
        assert store.get("product") == 200

    def test_empty_dataflow_block(self):
        """Empty @dataflow: block is valid."""
        # Actually empty blocks won't parse (grammar requires 1+ statements)
        # So test with a single statement
        store = run_kir("""\
x = 5
@dataflow:
    (x)identity(y)
""")
        assert store.get("y") == 5


# ===========================================================================
# 2. Dataflow block BEFORE control flow
# ===========================================================================


class TestDataflowBeforeControlFlow:
    def test_dataflow_produces_loop_vars(self):
        """Dataflow block sets up variables used by a loop."""
        store = run_kir("""\
@dataflow:
    (5)to_float(limit)
    (0)to_float(counter)
    (1)to_float(step)

()jump(`loop`)
loop:
    (counter, step)add(counter)
    (counter, limit)less_than(keep)
    (keep)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:
""")
        assert store.get("counter") == 5.0
        assert store.get("limit") == 5.0

    def test_dataflow_produces_branch_condition_input(self):
        """Dataflow block produces a value used as branch input."""
        store = run_kir("""\
@dataflow:
    (10)to_float(x)
    (5)to_float(threshold)
    (x, threshold)greater_than(is_big)

(is_big)branch(`big`, `small`)
big:
    (x, 2)multiply(result)
small:
    (x, 2)divide(result)
""")
        assert store.get("result") == 20.0  # 10 > 5, so big path


# ===========================================================================
# 3. Control flow BEFORE dataflow
# ===========================================================================


class TestControlFlowBeforeDataflow:
    def test_loop_output_used_by_dataflow(self):
        """Loop produces a value, then dataflow block consumes it."""
        store = run_kir("""\
counter = 0
limit = 5
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, limit)less_than(keep)
    (keep)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:

@dataflow:
    (counter)to_string(count_str)
    ("Count: ", count_str)concat(message)
""")
        assert store.get("counter") == 5
        assert store.get("message") == "Count: 5"

    def test_branch_output_used_by_dataflow(self):
        """Branch sets a variable, dataflow block uses it after."""
        store = run_kir("""\
x = 42
(x, 50)less_than(small)
(small)branch(`set_low`, `set_high`)
set_low:
    (x, 10)add(adjusted)
set_high:
    (x, 10)subtract(adjusted)

@dataflow:
    (adjusted)to_string(s)
    ("Adjusted: ", s)concat(msg)
""")
        assert store.get("adjusted") == 52  # 42 < 50, so set_low: 42+10
        assert store.get("msg") == "Adjusted: 52"


# ===========================================================================
# 4. Dataflow INSIDE a loop (re-executes each iteration)
# ===========================================================================


class TestDataflowInsideLoop:
    def test_dataflow_in_loop_body(self):
        """@dataflow: inside a loop re-executes each iteration."""
        store = run_kir("""\
counter = 0
total = 0
limit = 3
()jump(`loop`)
loop:
    (counter, 1)add(counter)

    @dataflow:
        (counter, counter)multiply(squared)
        (total, squared)add(total)

    (counter, limit)less_than(keep)
    (keep)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:
""")
        # counter goes 1, 2, 3
        # squared: 1, 4, 9
        # total: 0+1=1, 1+4=5, 5+9=14
        assert store.get("counter") == 3
        assert store.get("total") == 14

    def test_dataflow_in_branch_path(self):
        """@dataflow: inside a branch path executes only when that path is taken."""
        store = run_kir("""\
x = 10
(x, 5)greater_than(big)
(big)branch(`path_a`, `path_b`)
path_a:
    @dataflow:
        (x, 2)multiply(result)
        (result)to_string(result_str)
path_b:
    @dataflow:
        (x, 2)divide(result)
        (result)to_string(result_str)
""")
        assert store.get("result") == 20  # 10 > 5, path_a taken


# ===========================================================================
# 5. Multiple dataflow blocks
# ===========================================================================


class TestMultipleDataflowBlocks:
    def test_sequential_blocks(self):
        """Multiple @dataflow: blocks execute in file order."""
        store = run_kir("""\
@dataflow:
    (10)to_float(x)
    (20)to_float(y)

@dataflow:
    (x, y)add(sum)
    (x, y)multiply(product)
""")
        assert store.get("sum") == 30.0
        assert store.get("product") == 200.0

    def test_blocks_with_control_flow_between(self):
        """Dataflow blocks separated by control flow."""
        store = run_kir("""\
@dataflow:
    (10)to_float(x)
    (0)to_float(y)

(x, 5)greater_than(is_big)
(is_big)branch(`yes`, `no`)
yes:
    (100)to_float(y)
no:
    (0)to_float(y)

@dataflow:
    (x, y)add(total)
""")
        assert store.get("total") == 110.0  # 10 > 5, y=100, total=10+100


# ===========================================================================
# 6. Dependency ordering within @dataflow:
# ===========================================================================


class TestDependencyOrdering:
    def test_chain_reordered(self):
        """A→B→C chain written as C, A, B gets reordered to A, B, C."""
        before, after = compile_and_show("""\
@dataflow:
    (b)identity(c)
    ()identity(a)
    (a)identity(b)
""")
        assert "@dataflow:" in before
        assert "@dataflow:" not in after
        # In the compiled output, find the order
        compiled = compile_kir("""\
@dataflow:
    (b)identity(c)
    ()identity(a)
    (a)identity(b)
""")
        names = []
        for s in compiled.body:
            if isinstance(s, FuncCall):
                out = s.outputs[0] if s.outputs else "?"
                names.append(out)
        # a must come before b, b before c
        assert names.index("a") < names.index("b")
        assert names.index("b") < names.index("c")

    def test_independent_nodes_both_present(self):
        """Independent nodes in @dataflow: are all emitted."""
        store = run_kir("""\
@dataflow:
    (10)to_float(a)
    (20)to_float(b)
    (30)to_float(c)
""")
        assert store.get("a") == 10.0
        assert store.get("b") == 20.0
        assert store.get("c") == 30.0

    def test_diamond_dependency(self):
        """Diamond: A→B, A→C, B+C→D."""
        store = run_kir("""\
@dataflow:
    (b, c)add(d)
    (a, 1)add(b)
    (a, 2)add(c)
    (10)to_float(a)
""")
        # a=10, b=11, c=12, d=23
        assert store.get("a") == 10.0
        assert store.get("b") == 11.0
        assert store.get("c") == 12.0
        assert store.get("d") == 23.0


# ===========================================================================
# 7. Dataflow with external variable inputs
# ===========================================================================


class TestExternalInputs:
    def test_uses_var_from_before(self):
        """@dataflow: block uses a variable defined before it."""
        store = run_kir("""\
base = 100
@dataflow:
    (base, 10)add(x)
    (base, 20)add(y)
""")
        assert store.get("x") == 110
        assert store.get("y") == 120

    def test_uses_var_from_assignment(self):
        """@dataflow: block uses a variable from an assignment."""
        store = run_kir("""\
factor = 3
@dataflow:
    (10, factor)multiply(result)
""")
        assert store.get("result") == 30

    def test_output_used_after(self):
        """Variable from @dataflow: block is accessible after it."""
        store = run_kir("""\
@dataflow:
    (5, 3)add(val)

(val, 2)multiply(doubled)
""")
        assert store.get("val") == 8
        assert store.get("doubled") == 16


# ===========================================================================
# 8. Compilation visibility (before/after)
# ===========================================================================


class TestCompilationVisibility:
    def test_show_reordering(self):
        """Verify the before/after text shows reordering."""
        before, after = compile_and_show("""\
x = 10
@dataflow:
    (x, y)multiply(product)
    (2)to_float(y)
    (product)to_string(s)
""")
        # Before: @dataflow: block present
        assert "@dataflow:" in before
        assert "(x, y)multiply(product)" in before

        # After: no @dataflow:, reordered
        assert "@dataflow:" not in after
        # to_float should come before multiply
        y_pos = after.index("to_float")
        mul_pos = after.index("multiply")
        assert y_pos < mul_pos

    def test_mixed_show_control_flow_preserved(self):
        """Control flow outside @dataflow: is not reordered."""
        before, after = compile_and_show("""\
counter = 0
()jump(`loop`)
loop:
    (counter, 1)add(counter)
    (counter, 3)less_than(keep)
    (keep)branch(`cont`, `done`)
    cont:
        ()jump(`loop`)
    done:

@dataflow:
    (counter)to_string(s)
""")
        # Jump should still be present and in order
        assert "jump(" in after
        assert "branch(" in after
        assert "@dataflow:" not in after


# ===========================================================================
# 9. Nested dataflow in various scopes
# ===========================================================================


class TestNestedDataflow:
    def test_dataflow_in_namespace(self):
        """@dataflow: inside a namespace works."""
        store = run_kir("""\
x = True
(x)branch(`path`, `other`)
path:
    @dataflow:
        (10, 20)add(result)
other:
    result = 0
""")
        assert store.get("result") == 30

    def test_dataflow_in_subgraph(self):
        """@dataflow: inside a @def subgraph works."""
        store = run_kir("""\
@def (a, b)compute(sum, product):
    @dataflow:
        (a, b)add(sum)
        (a, b)multiply(product)

(3, 7)compute(s, p)
""")
        assert store.get("s") == 10
        assert store.get("p") == 21


# ===========================================================================
# 10. Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_dataflow_single_statement(self):
        """@dataflow: with a single statement is valid."""
        store = run_kir("""\
@dataflow:
    (42)to_float(x)
""")
        assert store.get("x") == 42.0

    def test_dataflow_with_assignments(self):
        """@dataflow: can contain plain assignments."""
        store = run_kir("""\
@dataflow:
    x = 10
    y = 20
    (x, y)add(z)
""")
        assert store.get("z") == 30

    def test_dataflow_assignment_order_irrelevant(self):
        """Assignments in @dataflow: are treated as having no deps on each other."""
        store = run_kir("""\
@dataflow:
    (a, b)add(c)
    a = 5
    b = 10
""")
        assert store.get("c") == 15

    def test_multiple_outputs_from_one_call(self):
        """Function with multiple outputs in @dataflow:."""
        reg = make_registry()
        reg.register("split", lambda v: (v + 1, v - 1), output_names=["high", "low"])
        exe = Executor(registry=reg, validate=False)
        store = exe.execute_source("""\
@dataflow:
    (10)split(high, low)
    (high, low)add(span)
""")
        assert store.get("high") == 11
        assert store.get("low") == 9
        assert store.get("span") == 20

    def test_loop_with_internal_dataflow_accumulation(self):
        """Realistic: loop with @dataflow: computing intermediate values each iter."""
        store = run_kir("""\
i = 0
sum = 0
limit = 4
()jump(`loop`)
loop:
    (i, 1)add(i)

    @dataflow:
        (i, i)multiply(i_squared)
        (sum, i_squared)add(sum)

    (i, limit)less_than(cont)
    (cont)branch(`again`, `stop`)
    again:
        ()jump(`loop`)
    stop:
""")
        # i=1: sq=1, sum=1
        # i=2: sq=4, sum=5
        # i=3: sq=9, sum=14
        # i=4: sq=16, sum=30
        assert store.get("i") == 4
        assert store.get("sum") == 30
