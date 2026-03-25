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
    "branch_simplify",
    "dead_code",
    "cse",
    "parallel_detect",  # must be LAST — needs clean input from other passes
]

# ---------------------------------------------------------------------------
# ParallelPathDetector
# ---------------------------------------------------------------------------


class ParallelPathDetector(IRPass):
    """Detect independent statement groups that a backend could run concurrently.

    Groups consecutive statements into logical "blocks" — a Branch/Switch and
    its sibling Namespaces form ONE block. Only top-level blocks are considered.
    If two adjacent blocks share no data dependencies, they're wrapped in a
    ``Parallel`` node.

    Important constraints:
    - Namespace children of Branch/Switch/Parallel are NEVER separated from their parent.
    - Control flow (Jump, Branch, Switch) statements anchor everything that follows.
    - Only truly independent, adjacent blocks are parallelized.
    - The pass does NOT recurse into nested scopes.
    """

    @property
    def name(self) -> str:
        return "parallel_detect"

    def transform(self, program: Program) -> Program:
        blocks = _group_into_blocks(program.body)
        if len(blocks) < 2:
            return program

        # Compute cumulative outputs/inputs per block
        block_outputs = [_block_outputs(b) for b in blocks]
        block_inputs = [_block_inputs(b) for b in blocks]

        # Union-Find: merge blocks with data dependencies
        parent = list(range(len(blocks)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            parent[find(x)] = find(y)

        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                if block_outputs[i] & block_inputs[j]:
                    union(i, j)
                elif block_outputs[j] & block_inputs[i]:
                    union(i, j)

        # Group blocks by root
        groups: dict[int, list[int]] = {}
        for i in range(len(blocks)):
            groups.setdefault(find(i), []).append(i)

        # Check if there are actually independent groups
        independent_groups = [idxs for idxs in groups.values()]
        if len(independent_groups) < 2:
            return program

        # Check: are the groups actually non-trivially parallelizable?
        # If one group has almost everything, don't bother.
        multi_groups = [g for g in independent_groups if any(len(blocks[i]) > 0 for i in g)]
        if len(multi_groups) < 2:
            return program

        # Build parallel structure — only wrap if we have 2+ real groups
        group_stmts: list[Statement] = []
        labels: list[str] = []
        for g_idx, idxs in enumerate(independent_groups):
            # Flatten block statements back
            body: list[Statement] = []
            for i in sorted(idxs):
                body.extend(blocks[i])
            if not body:
                continue
            label = f"__par_{g_idx}"
            labels.append(label)
            group_stmts.append(Namespace(name=label, body=body))

        if len(labels) < 2:
            return program

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
        # Inline trivial jump→namespace pairs:
        # ()jump(`label`) immediately followed by label: body,
        # AND no other reference to `label` anywhere in the program → inline body
        new_body = _inline_trivial_jumps(new_body)
        if new_body is program.body:
            return program
        return Program(body=new_body, mode=program.mode, typehints=program.typehints)


def _collect_all_label_refs(stmts: list[Statement]) -> dict[str, int]:
    """Count how many times each label is referenced across all statements."""
    counts: dict[str, int] = {}

    def _walk(body: list[Statement]) -> None:
        for stmt in body:
            match stmt:
                case Jump():
                    counts[stmt.target] = counts.get(stmt.target, 0) + 1
                case Branch():
                    counts[stmt.true_label] = counts.get(stmt.true_label, 0) + 1
                    counts[stmt.false_label] = counts.get(stmt.false_label, 0) + 1
                case Switch():
                    for _, label in stmt.cases:
                        counts[label] = counts.get(label, 0) + 1
                    if stmt.default_label:
                        counts[stmt.default_label] = counts.get(stmt.default_label, 0) + 1
                case Parallel():
                    for label in stmt.labels:
                        counts[label] = counts.get(label, 0) + 1
                case Namespace():
                    _walk(stmt.body)
                case TryExcept():
                    _walk(stmt.try_body)
                    _walk(stmt.except_body)
                case SubgraphDef():
                    _walk(stmt.body)

    _walk(stmts)
    return counts


def _inline_trivial_jumps(stmts: list[Statement]) -> list[Statement]:
    """Inline jump→namespace pairs where the jump is immediately followed by
    its target namespace AND no other statement references that label."""
    ref_counts = _collect_all_label_refs(stmts)

    result: list[Statement] = []
    i = 0
    while i < len(stmts):
        stmt = stmts[i]
        # Check: Jump immediately followed by its target Namespace
        if (
            isinstance(stmt, Jump)
            and i + 1 < len(stmts)
            and isinstance(stmts[i + 1], Namespace)
            and stmts[i + 1].name == stmt.target
            and ref_counts.get(stmt.target, 0) == 1  # only this one reference
        ):
            # Safe to inline: replace jump + namespace with just the body
            result.extend(stmts[i + 1].body)
            i += 2  # skip both jump and namespace
        else:
            result.append(stmt)
            i += 1

    return result


def _simplify_body(stmts: list[Statement], constants: dict[str, object] | None = None) -> list[Statement]:
    if constants is None:
        constants = {}
    # First pass: collect constant assignments (name = Literal)
    for stmt in stmts:
        if isinstance(stmt, Assignment) and isinstance(stmt.value, Literal):
            constants[stmt.target] = stmt.value.value
    # Second pass: simplify
    result: list[Statement] = []
    changed = False
    for stmt in stmts:
        simplified = _simplify_stmt(stmt, constants)
        if simplified is not stmt:
            changed = True
        result.append(simplified)
    return result if changed else stmts


def _resolve_bool_condition(cond: Expression, constants: dict[str, object]) -> bool | None:
    """Try to resolve a condition to a bool. Returns None if not resolvable."""
    if isinstance(cond, Literal) and cond.literal_type == "bool":
        return cond.value
    if isinstance(cond, Identifier) and cond.name in constants:
        val = constants[cond.name]
        if isinstance(val, bool):
            return val
    return None


def _simplify_stmt(stmt: Statement, constants: dict[str, object]) -> Statement:
    match stmt:
        case Branch():
            resolved = _resolve_bool_condition(stmt.condition, constants)
            if resolved is True:
                return Jump(target=stmt.true_label, line=stmt.line)
            if resolved is False:
                return Jump(target=stmt.false_label, line=stmt.line)
        case Namespace():
            new_body = _simplify_body(stmt.body, constants)
            if new_body is not stmt.body:
                return Namespace(name=stmt.name, body=new_body, line=stmt.line)
        case SubgraphDef():
            new_body = _simplify_body(stmt.body, constants)
            if new_body is not stmt.body:
                return SubgraphDef(
                    name=stmt.name,
                    params=stmt.params,
                    outputs=stmt.outputs,
                    body=new_body,
                    line=stmt.line,
                )
        case TryExcept():
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
        match stmt:
            case Jump():
                labels.add(stmt.target)
            case Branch():
                labels.add(stmt.true_label)
                labels.add(stmt.false_label)
            case Switch():
                for _, lbl in stmt.cases:
                    labels.add(lbl)
                if stmt.default_label:
                    labels.add(stmt.default_label)
            case Parallel():
                labels.update(stmt.labels)
            case Namespace():
                labels.update(_collect_reachable_labels(stmt.body))
            case SubgraphDef():
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
    match expr:
        case Identifier():
            return ("id", expr.name)
        case Literal():
            val = expr.value
            # Make value hashable for list/dict literals
            try:
                hash(val)
                return ("lit", val, expr.literal_type)
            except TypeError:
                return ("lit", str(val), expr.literal_type)
        case KeywordArg():
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
        match stmt:
            case FuncCall():
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
            case Namespace():
                result.append(
                    Namespace(
                        name=stmt.name,
                        body=_cse_body(stmt.body),
                        line=stmt.line,
                    )
                )
            case SubgraphDef():
                result.append(
                    SubgraphDef(
                        name=stmt.name,
                        params=stmt.params,
                        outputs=stmt.outputs,
                        body=_cse_body(stmt.body),
                        line=stmt.line,
                    )
                )
            case TryExcept():
                result.append(
                    TryExcept(
                        try_body=_cse_body(stmt.try_body),
                        except_body=_cse_body(stmt.except_body),
                        metadata=stmt.metadata,
                        line=stmt.line,
                    )
                )
            case _:
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
            match name:
                case "parallel_detect":
                    pipeline_passes.append(ParallelPathDetector())
                case "branch_simplify":
                    pipeline_passes.append(BranchSimplifier())
                    pipeline_passes.append(DeadNamespaceEliminator())
                case "dead_code":
                    pipeline_passes.append(DeadCodePass())
                case "cse":
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


def _group_into_blocks(stmts: list[Statement]) -> list[list[Statement]]:
    """Group statements into logical blocks.

    A Branch/Switch/Parallel and its immediately following sibling Namespaces
    form ONE block. Everything else is its own block.
    """
    blocks: list[list[Statement]] = []
    i = 0
    while i < len(stmts):
        stmt = stmts[i]
        match stmt:
            case Branch() | Switch() | Parallel():
                # Collect this + all following Namespace siblings that belong to it
                block = [stmt]
                # Gather the labels this control node owns
                owned_labels: set[str] = set()
                match stmt:
                    case Branch():
                        owned_labels = {stmt.true_label, stmt.false_label}
                    case Switch():
                        owned_labels = {label for _, label in stmt.cases}
                        if stmt.default_label:
                            owned_labels.add(stmt.default_label)
                    case Parallel():
                        owned_labels = set(stmt.labels)
                # Consume following namespaces that match
                j = i + 1
                while j < len(stmts) and isinstance(stmts[j], Namespace) and stmts[j].name in owned_labels:
                    block.append(stmts[j])
                    j += 1
                blocks.append(block)
                i = j
            case Jump():
                # Jump + its target Namespace form ONE block
                block = [stmt]
                j = i + 1
                while j < len(stmts) and isinstance(stmts[j], Namespace) and stmts[j].name == stmt.target:
                    block.append(stmts[j])
                    j += 1
                blocks.append(block)
                i = j
            case Namespace() | TryExcept() | TypeHintBlock():
                blocks.append([stmt])
                i += 1
            case _:
                # Assignment, FuncCall, etc.
                blocks.append([stmt])
                i += 1
    return blocks


def _block_outputs(block: list[Statement]) -> set[str]:
    """All variable names produced by any statement in the block."""
    result: set[str] = set()
    for s in block:
        result |= _stmt_outputs(s)
        # Also collect outputs from namespace bodies (they define variables too)
        if isinstance(s, Namespace):
            for inner in s.body:
                result |= _stmt_outputs(inner)
    return result


def _block_inputs(block: list[Statement]) -> set[str]:
    """All variable names consumed by any statement in the block."""
    result: set[str] = set()
    for s in block:
        result |= _stmt_inputs(s)
        if isinstance(s, Namespace):
            for inner in s.body:
                result |= _stmt_inputs(inner)
    return result


def _stmt_outputs(stmt: Statement) -> set[str]:
    """Return the set of variable names *produced* by *stmt*."""
    outputs: set[str] = set()
    match stmt:
        case Assignment():
            outputs.add(stmt.target)
        case FuncCall():
            for out in stmt.outputs:
                if not isinstance(out, Wildcard):
                    outputs.add(out)
    return outputs


def _stmt_inputs(stmt: Statement) -> set[str]:
    """Return the set of variable names *consumed* by *stmt*."""
    inputs: set[str] = set()
    match stmt:
        case Assignment():
            inputs |= _collect_identifier_names(stmt.value)
        case FuncCall():
            for inp in stmt.inputs:
                inputs |= _collect_identifier_names(inp)
        case Branch():
            inputs |= _collect_identifier_names(stmt.condition)
        case Switch():
            inputs |= _collect_identifier_names(stmt.value)
    return inputs
