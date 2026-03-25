"""L4 optimizer: ParallelPathDetector, BranchSimplifier, DeadCodeEliminator, CSE."""

from __future__ import annotations

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    Expression,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    Literal,
    Namespace,
    Parallel,
    Program,
    Statement,
    SubgraphDef,
    Switch,
    TryExcept,
    TypeHintBlock,
    Wildcard,
)
from kohakunode.compiler.dead_code import DeadCodePass
from kohakunode.compiler.passes import IRPass, PassPipeline, _collect_identifier_names

# ---------------------------------------------------------------------------
# Known sub-pass names (for validation / ordering)
# ---------------------------------------------------------------------------

_ALL_PASSES: list[str] = [
    "parallel_detect",
    "branch_simplify",
    "dead_code",
    "cse",
]

# ---------------------------------------------------------------------------
# ParallelPathDetector
# ---------------------------------------------------------------------------


class ParallelPathDetector(IRPass):
    """Detect independent statement sequences and annotate them with metadata.

    Two statements are *independent* when neither produces any variable
    consumed by the other (directly or transitively through intervening
    statements).  Independent runs are wrapped in a
    :class:`~kohakunode.ast.nodes.Parallel` node whose ``labels`` are set to
    the string ``"__parallel_group__"`` plus an index.

    The detector operates on the *flat* top-level body only (no recursion into
    Namespace / SubgraphDef scopes) so that it cannot misidentify control-flow
    boundaries as parallelisable.

    Implementation note
    -------------------
    This is a conservative union-find approach: each statement starts in its
    own group.  For every pair of statements (i, j) where i < j, if the
    *outputs* of statement i appear in the *inputs* of statement j (or vice
    versa) the two groups are merged.  After merging, groups with more than
    one member whose statements are not interleaved with dependent statements
    become candidates for a ``Parallel`` wrapper.

    For simplicity the emitted ``Parallel`` node carries numeric group labels
    ``"__parallel_group_0"``, ``"__parallel_group_1"``, … and each group's
    statements are wrapped in a :class:`~kohakunode.ast.nodes.Namespace` with
    the matching name so that the runtime can dispatch them concurrently.
    """

    @property
    def name(self) -> str:
        return "parallel_detect"

    def transform(self, program: Program) -> Program:
        stmts = program.body
        if len(stmts) < 2:
            return program

        outputs_per_stmt = [_stmt_outputs(s) for s in stmts]
        inputs_per_stmt = [_stmt_inputs(s) for s in stmts]

        # Union-Find
        parent = list(range(len(stmts)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            parent[find(x)] = find(y)

        # Merge any two stmts that share a data dependency
        for i in range(len(stmts)):
            for j in range(i + 1, len(stmts)):
                # i produces something j consumes
                if outputs_per_stmt[i] & inputs_per_stmt[j]:
                    union(i, j)
                # j produces something i consumes
                elif outputs_per_stmt[j] & inputs_per_stmt[i]:
                    union(i, j)

        # Group statements by root
        groups: dict[int, list[int]] = {}
        for i in range(len(stmts)):
            root = find(i)
            groups.setdefault(root, []).append(i)

        # Only transform when there are at least 2 independent groups
        independent_groups = [idxs for idxs in groups.values() if len(idxs) >= 1]
        if len(independent_groups) < 2:
            return program

        # Assign a label to each group and build namespace wrappers
        group_stmts: list[Statement] = []
        labels: list[str] = []
        for g_idx, idxs in enumerate(independent_groups):
            label = f"__parallel_group_{g_idx}"
            labels.append(label)
            ns_body = [stmts[i] for i in sorted(idxs)]
            group_stmts.append(Namespace(name=label, body=ns_body))

        new_body: list[Statement] = list(group_stmts)
        new_body.append(Parallel(labels=labels))

        return Program(body=new_body, mode=program.mode, typehints=program.typehints)


# ---------------------------------------------------------------------------
# BranchSimplifier
# ---------------------------------------------------------------------------


class BranchSimplifier(IRPass):
    """Replace Branch nodes with literal conditions with just the taken arm.

    If the condition of a :class:`~kohakunode.ast.nodes.Branch` is a
    :class:`~kohakunode.ast.nodes.Literal` ``True`` or ``False``, the branch
    is replaced by an unconditional
    :class:`~kohakunode.ast.nodes.Jump` to the chosen label.
    """

    @property
    def name(self) -> str:
        return "branch_simplify"

    def transform(self, program: Program) -> Program:
        new_body = _simplify_body(program.body)
        if new_body is program.body:
            return program
        return Program(body=new_body, mode=program.mode, typehints=program.typehints)


def _simplify_body(stmts: list[Statement]) -> list[Statement]:
    result: list[Statement] = []
    changed = False
    for stmt in stmts:
        simplified = _simplify_stmt(stmt)
        if simplified is not stmt:
            changed = True
        result.append(simplified)
    return result if changed else stmts


def _simplify_stmt(stmt: Statement) -> Statement:
    if isinstance(stmt, Branch):
        cond = stmt.condition
        if isinstance(cond, Literal) and cond.literal_type == "bool":
            if cond.value is True:
                return Jump(target=stmt.true_label, line=stmt.line)
            if cond.value is False:
                return Jump(target=stmt.false_label, line=stmt.line)
    elif isinstance(stmt, Namespace):
        new_body = _simplify_body(stmt.body)
        if new_body is not stmt.body:
            return Namespace(name=stmt.name, body=new_body, line=stmt.line)
    elif isinstance(stmt, SubgraphDef):
        new_body = _simplify_body(stmt.body)
        if new_body is not stmt.body:
            return SubgraphDef(
                name=stmt.name,
                params=stmt.params,
                outputs=stmt.outputs,
                body=new_body,
                line=stmt.line,
            )
    elif isinstance(stmt, TryExcept):
        new_try = _simplify_body(stmt.try_body)
        new_except = _simplify_body(stmt.except_body)
        if new_try is not stmt.try_body or new_except is not stmt.except_body:
            return TryExcept(
                try_body=new_try,
                except_body=new_except,
                metadata=stmt.metadata,
                line=stmt.line,
            )
    return stmt


# ---------------------------------------------------------------------------
# DeadNamespaceEliminator
# ---------------------------------------------------------------------------


class DeadNamespaceEliminator(IRPass):
    """Remove Namespace nodes that are unreachable after branch simplification.

    A namespace is *unreachable* when it is never the target of any
    :class:`~kohakunode.ast.nodes.Jump`,
    :class:`~kohakunode.ast.nodes.Branch`,
    :class:`~kohakunode.ast.nodes.Switch`, or
    :class:`~kohakunode.ast.nodes.Parallel` node in the same program body.

    This is intentionally conservative: if any reachability information is
    ambiguous (e.g. the target is computed at runtime) the namespace is kept.
    """

    @property
    def name(self) -> str:
        return "dead_namespace"

    def transform(self, program: Program) -> Program:
        reachable = _collect_reachable_labels(program.body)
        new_body = _remove_unreachable_namespaces(program.body, reachable)
        if new_body == program.body:
            return program
        return Program(body=new_body, mode=program.mode, typehints=program.typehints)


def _collect_reachable_labels(stmts: list[Statement]) -> set[str]:
    labels: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, Jump):
            labels.add(stmt.target)
        elif isinstance(stmt, Branch):
            labels.add(stmt.true_label)
            labels.add(stmt.false_label)
        elif isinstance(stmt, Switch):
            for _, lbl in stmt.cases:
                labels.add(lbl)
            if stmt.default_label:
                labels.add(stmt.default_label)
        elif isinstance(stmt, Parallel):
            labels.update(stmt.labels)
        elif isinstance(stmt, Namespace):
            labels.update(_collect_reachable_labels(stmt.body))
        elif isinstance(stmt, SubgraphDef):
            labels.update(_collect_reachable_labels(stmt.body))
    return labels


def _remove_unreachable_namespaces(
    stmts: list[Statement], reachable: set[str]
) -> list[Statement]:
    result = []
    for stmt in stmts:
        if isinstance(stmt, Namespace):
            if stmt.name not in reachable:
                # Unreachable — drop it
                continue
            # Recurse
            new_body = _remove_unreachable_namespaces(stmt.body, reachable)
            result.append(Namespace(name=stmt.name, body=new_body, line=stmt.line))
        else:
            result.append(stmt)
    return result


# ---------------------------------------------------------------------------
# CommonSubexprEliminator
# ---------------------------------------------------------------------------


class CommonSubexprEliminator(IRPass):
    """Eliminate duplicate FuncCalls with identical func_name + inputs.

    When two :class:`~kohakunode.ast.nodes.FuncCall` nodes have the same
    ``func_name`` and structurally identical ``inputs`` the second call is
    replaced by :class:`~kohakunode.ast.nodes.Assignment` statements that
    bind the second call's output names to the first call's output names.

    Inputs are compared structurally: two
    :class:`~kohakunode.ast.nodes.Identifier` nodes are equal when their
    ``name`` fields match; two :class:`~kohakunode.ast.nodes.Literal` nodes
    are equal when both ``value`` and ``literal_type`` match.

    Only concrete (non-wildcard) outputs are subject to CSE.
    """

    @property
    def name(self) -> str:
        return "cse"

    def transform(self, program: Program) -> Program:
        new_body = _cse_body(program.body)
        return Program(body=new_body, mode=program.mode, typehints=program.typehints)


def _expr_key(expr: Expression) -> object:
    """Return a hashable key for structural expression equality."""
    if isinstance(expr, Identifier):
        return ("id", expr.name)
    if isinstance(expr, Literal):
        val = expr.value
        # Make value hashable for list/dict literals
        try:
            hash(val)
            return ("lit", val, expr.literal_type)
        except TypeError:
            return ("lit", str(val), expr.literal_type)
    if isinstance(expr, KeywordArg):
        return ("kw", expr.name, _expr_key(expr.value))
    return ("other", repr(expr))


def _call_key(stmt: FuncCall) -> tuple:
    """Return a hashable key identifying this call's func_name + inputs."""
    return (stmt.func_name, tuple(_expr_key(inp) for inp in stmt.inputs))


def _cse_body(stmts: list[Statement]) -> list[Statement]:
    # Map: call_key -> list of concrete output names produced by the first call
    seen: dict[tuple, list[str]] = {}
    result: list[Statement] = []

    for stmt in stmts:
        if isinstance(stmt, FuncCall):
            key = _call_key(stmt)
            concrete_outputs = [
                out for out in stmt.outputs if not isinstance(out, Wildcard)
            ]
            if key in seen and concrete_outputs:
                first_outputs = seen[key]
                # Replace with assignments: new_out = first_out
                for new_name, orig_name in zip(concrete_outputs, first_outputs):
                    result.append(
                        Assignment(
                            target=new_name,
                            value=Identifier(name=orig_name),
                            line=stmt.line,
                        )
                    )
            else:
                if concrete_outputs:
                    seen[key] = concrete_outputs
                result.append(stmt)
        elif isinstance(stmt, Namespace):
            result.append(
                Namespace(
                    name=stmt.name,
                    body=_cse_body(stmt.body),
                    line=stmt.line,
                )
            )
        elif isinstance(stmt, SubgraphDef):
            result.append(
                SubgraphDef(
                    name=stmt.name,
                    params=stmt.params,
                    outputs=stmt.outputs,
                    body=_cse_body(stmt.body),
                    line=stmt.line,
                )
            )
        elif isinstance(stmt, TryExcept):
            result.append(
                TryExcept(
                    try_body=_cse_body(stmt.try_body),
                    except_body=_cse_body(stmt.except_body),
                    metadata=stmt.metadata,
                    line=stmt.line,
                )
            )
        else:
            result.append(stmt)

    return result


# ---------------------------------------------------------------------------
# Optimizer (L4)
# ---------------------------------------------------------------------------


class Optimizer(IRPass):
    """L4 optimizer that composes configurable sub-passes.

    Parameters
    ----------
    passes:
        Ordered list of sub-pass names to enable.  Defaults to all four:
        ``["parallel_detect", "branch_simplify", "dead_code", "cse"]``.

        Available names:

        * ``"parallel_detect"`` — :class:`ParallelPathDetector`
        * ``"branch_simplify"`` — :class:`BranchSimplifier` + dead-namespace removal
        * ``"dead_code"``       — :class:`DeadCodePass`
        * ``"cse"``             — :class:`CommonSubexprEliminator`
    """

    def __init__(self, passes: list[str] | None = None) -> None:
        selected = passes if passes is not None else list(_ALL_PASSES)
        # Validate
        unknown = set(selected) - set(_ALL_PASSES)
        if unknown:
            raise ValueError(
                f"Unknown optimizer sub-pass(es): {sorted(unknown)}. "
                f"Valid options: {_ALL_PASSES}"
            )

        pipeline_passes: list[IRPass] = []
        for name in selected:
            if name == "parallel_detect":
                pipeline_passes.append(ParallelPathDetector())
            elif name == "branch_simplify":
                pipeline_passes.append(BranchSimplifier())
                pipeline_passes.append(DeadNamespaceEliminator())
            elif name == "dead_code":
                pipeline_passes.append(DeadCodePass())
            elif name == "cse":
                pipeline_passes.append(CommonSubexprEliminator())

        self._pipeline = PassPipeline(pipeline_passes)

    @property
    def name(self) -> str:
        return "optimizer"

    def transform(self, program: Program) -> Program:
        return self._pipeline.transform(program)


# ---------------------------------------------------------------------------
# Internal utility: collect outputs / inputs of a statement
# ---------------------------------------------------------------------------


def _stmt_outputs(stmt: Statement) -> set[str]:
    """Return the set of variable names *produced* by *stmt*."""
    outputs: set[str] = set()
    if isinstance(stmt, Assignment):
        outputs.add(stmt.target)
    elif isinstance(stmt, FuncCall):
        for out in stmt.outputs:
            if not isinstance(out, Wildcard):
                outputs.add(out)
    return outputs


def _stmt_inputs(stmt: Statement) -> set[str]:
    """Return the set of variable names *consumed* by *stmt*."""
    inputs: set[str] = set()
    if isinstance(stmt, Assignment):
        inputs |= _collect_identifier_names(stmt.value)
    elif isinstance(stmt, FuncCall):
        for inp in stmt.inputs:
            inputs |= _collect_identifier_names(inp)
    elif isinstance(stmt, Branch):
        inputs |= _collect_identifier_names(stmt.condition)
    elif isinstance(stmt, Switch):
        inputs |= _collect_identifier_names(stmt.value)
    return inputs
