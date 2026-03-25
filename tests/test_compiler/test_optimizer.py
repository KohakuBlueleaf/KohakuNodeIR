"""L4 optimizer tests.

Covers:
- BranchSimplifier: literal True condition → only true arm (Jump)
- BranchSimplifier: literal False condition → only false arm (Jump)
- ParallelPathDetector: two independent sequences detected and wrapped
- DeadNamespaceEliminator: unreachable namespace removed after branch simplification
- Optimizer class: composes sub-passes correctly
- CommonSubexprEliminator: duplicate calls replaced with assignments
"""

import pytest

from kohakunode import parse
from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Jump,
    Namespace,
    Parallel,
    Program,
)
from kohakunode.compiler.optimizer import (
    BranchSimplifier,
    CommonSubexprEliminator,
    DeadNamespaceEliminator,
    Optimizer,
    ParallelPathDetector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stmt_types(prog: Program) -> list[str]:
    """Return list of statement type names in the top-level body."""
    return [type(s).__name__ for s in prog.body]


def _find_all(prog: Program, cls) -> list:
    return [s for s in prog.body if isinstance(s, cls)]


# ---------------------------------------------------------------------------
# BranchSimplifier
# ---------------------------------------------------------------------------


class TestBranchSimplifier:
    def test_literal_true_becomes_jump_to_true_label(self) -> None:
        """(True)branch(`yes`, `no`) → ()jump(`yes`)."""
        src = """\
(True)branch(`yes`, `no`)
yes:
    result = 1
no:
    result = 0
"""
        prog = parse(src)
        result = BranchSimplifier().transform(prog)
        jumps = _find_all(result, Jump)
        assert len(jumps) >= 1
        assert jumps[0].target == "yes"
        # No Branch nodes remain
        branches = _find_all(result, Branch)
        assert len(branches) == 0

    def test_literal_false_becomes_jump_to_false_label(self) -> None:
        """(False)branch(`yes`, `no`) → ()jump(`no`)."""
        src = """\
(False)branch(`yes`, `no`)
yes:
    result = 1
no:
    result = 0
"""
        prog = parse(src)
        result = BranchSimplifier().transform(prog)
        jumps = _find_all(result, Jump)
        assert len(jumps) >= 1
        assert jumps[0].target == "no"
        branches = _find_all(result, Branch)
        assert len(branches) == 0

    def test_dynamic_branch_not_simplified(self) -> None:
        """Branch with non-literal condition is not modified."""
        src = """\
cond = True
(cond)branch(`yes`, `no`)
yes:
    result = 1
no:
    result = 0
"""
        prog = parse(src)
        result = BranchSimplifier().transform(prog)
        # cond is a variable, not a literal → branch remains
        branches = _find_all(result, Branch)
        assert len(branches) == 1

    def test_nested_branch_simplified(self) -> None:
        """Literal branch inside a Namespace body is simplified."""
        src = """\
outer:
    (True)branch(`inner_yes`, `inner_no`)
    inner_yes:
        x = 1
    inner_no:
        x = 0
"""
        prog = parse(src)
        result = BranchSimplifier().transform(prog)
        nss = _find_all(result, Namespace)
        assert len(nss) >= 1
        # The outer namespace body should contain a Jump, not a Branch
        outer_body = nss[0].body
        has_jump = any(isinstance(s, Jump) for s in outer_body)
        has_branch = any(isinstance(s, Branch) for s in outer_body)
        assert has_jump
        assert not has_branch

    def test_simplifier_preserves_other_stmts(self) -> None:
        """Non-branch statements are not affected."""
        src = """\
x = 10
y = 20
(True)branch(`a`, `b`)
a:
    z = 1
b:
    z = 0
"""
        prog = parse(src)
        result = BranchSimplifier().transform(prog)
        assigns = [s for s in result.body if isinstance(s, Assignment)]
        names = {a.target for a in assigns}
        assert "x" in names
        assert "y" in names

    def test_pass_name(self) -> None:
        assert BranchSimplifier().name == "branch_simplify"


# ---------------------------------------------------------------------------
# DeadNamespaceEliminator
# ---------------------------------------------------------------------------


class TestDeadNamespaceEliminator:
    def test_unreachable_namespace_removed(self) -> None:
        """A namespace that no jump/branch targets is removed."""
        src = """\
x = 1
()jump(`used_ns`)
used_ns:
    y = 2
unused_ns:
    z = 99
"""
        prog = parse(src)
        result = DeadNamespaceEliminator().transform(prog)
        ns_names = {s.name for s in result.body if isinstance(s, Namespace)}
        assert "used_ns" in ns_names
        assert "unused_ns" not in ns_names

    def test_reachable_namespace_kept(self) -> None:
        """A namespace referenced by a Jump is kept."""
        src = """\
()jump(`my_ns`)
my_ns:
    x = 1
"""
        prog = parse(src)
        result = DeadNamespaceEliminator().transform(prog)
        ns_names = {s.name for s in result.body if isinstance(s, Namespace)}
        assert "my_ns" in ns_names

    def test_branch_target_namespaces_kept(self) -> None:
        """Both branch targets are kept."""
        src = """\
cond = True
(cond)branch(`yes`, `no`)
yes:
    result = 1
no:
    result = 0
unreachable_ns:
    dead = 99
"""
        prog = parse(src)
        result = DeadNamespaceEliminator().transform(prog)
        ns_names = {s.name for s in result.body if isinstance(s, Namespace)}
        assert "yes" in ns_names
        assert "no" in ns_names
        assert "unreachable_ns" not in ns_names

    def test_pass_name(self) -> None:
        assert DeadNamespaceEliminator().name == "dead_namespace"


# ---------------------------------------------------------------------------
# ParallelPathDetector
# ---------------------------------------------------------------------------


class TestParallelPathDetector:
    def test_two_independent_sequences_detected(self) -> None:
        """Two independent call chains → wrapped in Parallel."""
        src = """\
(1, 2)add(result_a)
(3, 4)add(result_b)
"""
        prog = parse(src)
        result = ParallelPathDetector().transform(prog)
        # Should have Namespace wrappers + one Parallel node
        parallels = _find_all(result, Parallel)
        assert len(parallels) == 1
        assert len(parallels[0].labels) == 2

    def test_dependent_sequence_not_split(self) -> None:
        """Dependent statements are kept in the same group."""
        src = """\
(1, 2)add(a)
(a, 3)add(b)
"""
        prog = parse(src)
        result = ParallelPathDetector().transform(prog)
        # a feeds b, so they are in the same dependency group
        # ParallelPathDetector should detect only 1 group → no Parallel emitted
        parallels = _find_all(result, Parallel)
        assert len(parallels) == 0

    def test_three_independent_groups(self) -> None:
        """Three mutually independent statements → three groups."""
        src = """\
a = 1
b = 2
c = 3
"""
        prog = parse(src)
        result = ParallelPathDetector().transform(prog)
        parallels = _find_all(result, Parallel)
        assert len(parallels) == 1
        assert len(parallels[0].labels) == 3

    def test_mixed_dependent_and_independent(self) -> None:
        """Chain A→B is one group, C is another independent group."""
        src = """\
a = 1
b = a
c = 99
"""
        prog = parse(src)
        result = ParallelPathDetector().transform(prog)
        parallels = _find_all(result, Parallel)
        # Two groups: {a, b} and {c}
        assert len(parallels) == 1
        assert len(parallels[0].labels) == 2

    def test_single_statement_no_parallel(self) -> None:
        """A single statement cannot form two groups."""
        src = "x = 1\n"
        prog = parse(src)
        result = ParallelPathDetector().transform(prog)
        parallels = _find_all(result, Parallel)
        assert len(parallels) == 0

    def test_parallel_groups_wrapped_in_namespaces(self) -> None:
        """Each parallel group is wrapped in a Namespace."""
        src = "(1, 2)add(a)\n(3, 4)add(b)\n"
        prog = parse(src)
        result = ParallelPathDetector().transform(prog)
        nss = _find_all(result, Namespace)
        assert len(nss) == 2
        # Each namespace name starts with "__parallel_group_"
        for ns in nss:
            assert ns.name.startswith("__parallel_group_")

    def test_pass_name(self) -> None:
        assert ParallelPathDetector().name == "parallel_detect"


# ---------------------------------------------------------------------------
# CommonSubexprEliminator
# ---------------------------------------------------------------------------


class TestCSE:
    def test_duplicate_call_replaced_with_assignment(self) -> None:
        """Two identical calls → second replaced by assignment."""
        src = "(1, 2)add(a)\n(1, 2)add(b)\n"
        prog = parse(src)
        result = CommonSubexprEliminator().transform(prog)
        calls = _find_all(result, FuncCall)
        assigns = _find_all(result, Assignment)
        # Only one actual call; the second is replaced by an assignment
        assert len(calls) == 1
        assert len(assigns) == 1
        assert assigns[0].target == "b"

    def test_different_calls_not_merged(self) -> None:
        """Different arguments → no CSE."""
        src = "(1, 2)add(a)\n(1, 3)add(b)\n"
        prog = parse(src)
        result = CommonSubexprEliminator().transform(prog)
        calls = _find_all(result, FuncCall)
        assert len(calls) == 2

    def test_different_functions_not_merged(self) -> None:
        """Same args, different function → no CSE."""
        src = "(1, 2)add(a)\n(1, 2)multiply(b)\n"
        prog = parse(src)
        result = CommonSubexprEliminator().transform(prog)
        calls = _find_all(result, FuncCall)
        assert len(calls) == 2

    def test_cse_pass_name(self) -> None:
        assert CommonSubexprEliminator().name == "cse"


# ---------------------------------------------------------------------------
# Optimizer class
# ---------------------------------------------------------------------------


class TestOptimizer:
    def test_optimizer_runs_all_passes(self) -> None:
        """Default Optimizer runs all four sub-passes without error."""
        src = """\
x = 1
y = 2
(x, y)add(sum)
(True)branch(`yes`, `no`)
yes:
    result = sum
no:
    result = 0
"""
        prog = parse(src)
        opt = Optimizer()
        result = opt.transform(prog)
        assert isinstance(result, Program)

    def test_optimizer_branch_simplify_only(self) -> None:
        """Optimizer with only branch_simplify converts literal branch to jump."""
        src = "(True)branch(`a`, `b`)\na:\n    x = 1\nb:\n    x = 0\n"
        prog = parse(src)
        result = Optimizer(passes=["branch_simplify"]).transform(prog)
        branches = _find_all(result, Branch)
        assert len(branches) == 0

    def test_optimizer_dead_code_only(self) -> None:
        """Optimizer with only dead_code removes unused assignments."""
        src = "unused = 42\nused = 99\n(used)print()\n"
        prog = parse(src)
        result = Optimizer(passes=["dead_code"]).transform(prog)
        assigns = _find_all(result, Assignment)
        names = {a.target for a in assigns}
        assert "unused" not in names
        assert "used" in names

    def test_optimizer_parallel_detect_only(self) -> None:
        """Optimizer with only parallel_detect wraps independent sequences."""
        src = "a = 1\nb = 2\n"
        prog = parse(src)
        result = Optimizer(passes=["parallel_detect"]).transform(prog)
        parallels = _find_all(result, Parallel)
        assert len(parallels) == 1

    def test_optimizer_unknown_pass_raises(self) -> None:
        """Unknown pass name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown optimizer sub-pass"):
            Optimizer(passes=["nonexistent_pass"])

    def test_optimizer_empty_passes_is_noop(self) -> None:
        """Optimizer with empty passes list is a no-op."""
        src = "x = 1\ny = x\n"
        prog = parse(src)
        result = Optimizer(passes=[]).transform(prog)
        names = {s.target for s in result.body if isinstance(s, Assignment)}
        assert "x" in names

    def test_optimizer_name(self) -> None:
        assert Optimizer().name == "optimizer"

    def test_branch_simplify_then_dead_namespace(self) -> None:
        """branch_simplify + dead_namespace removes false arm namespace."""
        src = """\
(True)branch(`taken`, `not_taken`)
taken:
    x = 1
not_taken:
    x = 0
"""
        prog = parse(src)
        result = Optimizer(passes=["branch_simplify"]).transform(prog)
        # After simplification, (True)branch → jump(`taken`)
        # not_taken should be removed by DeadNamespaceEliminator (included with branch_simplify)
        ns_names = {s.name for s in result.body if isinstance(s, Namespace)}
        assert "taken" in ns_names
        assert "not_taken" not in ns_names

    def test_full_optimizer_pipeline(self) -> None:
        """End-to-end: full pipeline produces a valid Program."""
        src = """\
x = 5
dead_var = 42
y = 10
(x, y)add(sum1)
(x, y)add(sum2)
"""
        prog = parse(src)
        result = Optimizer().transform(prog)
        assert isinstance(result, Program)
