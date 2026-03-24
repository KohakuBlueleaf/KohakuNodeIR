import abc
import collections

from kohakunode.ast.nodes import (
    Assignment,
    Expression,
    FuncCall,
    Identifier,
    KeywordArg,
    Namespace,
    Program,
    Statement,
    Wildcard,
)
from kohakunode.errors import KirCompilationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_identifier_names(expr: Expression) -> set[str]:
    """Recursively collect all Identifier names referenced in an expression."""
    names: set[str] = set()
    if isinstance(expr, Identifier):
        names.add(expr.name)
    elif isinstance(expr, KeywordArg):
        names |= _collect_identifier_names(expr.value)
    return names


# ---------------------------------------------------------------------------
# IRPass — abstract base class
# ---------------------------------------------------------------------------


class IRPass(abc.ABC):
    """Abstract base class for all IR transformation passes."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable name for this pass (used in logging/debugging)."""

    @abc.abstractmethod
    def transform(self, program: Program) -> Program:
        """Transform *program* and return the (possibly new) resulting Program."""

    def __repr__(self) -> str:
        return f"IRPass({self.name})"


# ---------------------------------------------------------------------------
# PassPipeline
# ---------------------------------------------------------------------------


class PassPipeline:
    """Chains multiple :class:`IRPass` instances together."""

    def __init__(self, passes: list[IRPass] | None = None) -> None:
        self._passes: list[IRPass] = list(passes) if passes is not None else []

    def add(self, pass_: IRPass) -> None:
        """Append *pass_* to the end of the pipeline."""
        self._passes.append(pass_)

    def transform(self, program: Program) -> Program:
        """Run all passes in order, feeding the output of each into the next."""
        result = program
        for pass_ in self._passes:
            result = pass_.transform(result)
        return result

    def __repr__(self) -> str:
        names = ", ".join(p.name for p in self._passes)
        return f"PassPipeline([{names}])"


# ---------------------------------------------------------------------------
# IdentityPass
# ---------------------------------------------------------------------------


class IdentityPass(IRPass):
    """A no-op pass that returns the program unchanged.

    Useful for testing the pipeline infrastructure.
    """

    @property
    def name(self) -> str:
        return "IdentityPass"

    def transform(self, program: Program) -> Program:
        return program


# ---------------------------------------------------------------------------
# DependencyGraphBuilder
# ---------------------------------------------------------------------------


class DependencyGraphBuilder:
    """Builds a variable-level dependency graph from a flat (non-control-flow) Program.

    For each statement that produces output variable names, maps each output
    name to the set of input variable names it depends on.  The resulting dict
    is used by the dataflow→sequential compiler to topologically sort nodes.
    """

    def build(self, program: Program) -> dict[str, set[str]]:
        """Analyze *program* and return an adjacency dict ``output_var → {input_vars}``.

        Supported statement kinds:

        * :class:`~kohakunode.ast.nodes.Assignment` — the target variable
          depends on every :class:`~kohakunode.ast.nodes.Identifier` referenced
          in the value expression.
        * :class:`~kohakunode.ast.nodes.FuncCall` — each non-wildcard output
          name depends on every :class:`~kohakunode.ast.nodes.Identifier` found
          in the input expressions.
        * :class:`~kohakunode.ast.nodes.Namespace` — skipped (should not exist
          in dataflow mode).
        """
        graph: dict[str, set[str]] = {}

        for stmt in program.body:
            if isinstance(stmt, Assignment):
                deps = _collect_identifier_names(stmt.value)
                graph[stmt.target] = deps

            elif isinstance(stmt, FuncCall):
                # Collect all identifier names from inputs
                input_names: set[str] = set()
                for inp in stmt.inputs:
                    input_names |= _collect_identifier_names(inp)

                # Collect output names for self-reference exclusion
                output_names: set[str] = set()
                for out in stmt.outputs:
                    if not isinstance(out, Wildcard):
                        output_names.add(out)

                # Map each concrete output name to those inputs,
                # excluding self-references (e.g., (total, x)add(total) is
                # an update, not a cycle)
                for out in stmt.outputs:
                    if isinstance(out, Wildcard):
                        continue
                    graph[out] = input_names - output_names

            elif isinstance(stmt, Namespace):
                # Namespaces should not appear in dataflow mode; skip silently.
                continue

        return graph


# ---------------------------------------------------------------------------
# topological_sort
# ---------------------------------------------------------------------------


def topological_sort(
    graph: dict[str, set[str]],
    statements: list[Statement],
) -> list[Statement]:
    """Return *statements* reordered according to a topological sort of *graph*.

    Uses Kahn's algorithm.

    Parameters
    ----------
    graph:
        Adjacency dict mapping each output variable name to the set of variable
        names it depends on (produced by :class:`DependencyGraphBuilder`).
    statements:
        The original flat statement list to reorder.

    Returns
    -------
    list[Statement]
        Statements in a valid execution order (dependencies before dependents).

    Raises
    ------
    KirCompilationError
        If a cycle is detected in the dependency graph.
    """
    # Build a mapping from output-variable name → statement for O(1) lookup.
    # A single statement may produce multiple outputs; each output key points
    # to the same statement object.
    var_to_stmt: dict[str, Statement] = {}
    for stmt in statements:
        if isinstance(stmt, Assignment):
            var_to_stmt[stmt.target] = stmt
        elif isinstance(stmt, FuncCall):
            for out in stmt.outputs:
                if not isinstance(out, Wildcard):
                    var_to_stmt[out] = stmt

    # Collect the set of all variables that appear in the graph as outputs.
    all_outputs: set[str] = set(graph.keys())

    # Compute in-degree for each output variable.
    # An edge A → B means "B depends on A", so B's in-degree increases for
    # each A that is itself a tracked output (i.e., produced by some node).
    in_degree: dict[str, int] = {var: 0 for var in all_outputs}
    # dependents[A] = set of output vars that depend on A
    dependents: dict[str, set[str]] = {var: set() for var in all_outputs}

    for var, deps in graph.items():
        for dep in deps:
            if dep in all_outputs:
                in_degree[var] += 1
                dependents[dep].add(var)

    # Kahn's algorithm — process nodes with in-degree 0 first.
    queue: collections.deque[str] = collections.deque(
        var for var in all_outputs if in_degree[var] == 0
    )

    # Track which statement objects have already been added to the result so
    # that statements with multiple outputs are not duplicated.
    seen_stmts: set[int] = set()  # id(stmt)
    sorted_stmts: list[Statement] = []
    processed_vars: list[str] = []

    while queue:
        var = queue.popleft()
        processed_vars.append(var)

        stmt = var_to_stmt.get(var)
        if stmt is not None and id(stmt) not in seen_stmts:
            seen_stmts.add(id(stmt))
            sorted_stmts.append(stmt)

        for dependent in dependents[var]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # If not all output variables were processed, there is a cycle.
    if len(processed_vars) != len(all_outputs):
        unresolved = all_outputs - set(processed_vars)
        raise KirCompilationError(
            f"Cycle detected in dependency graph involving variable(s): "
            f"{', '.join(sorted(unresolved))}"
        )

    # Statements that produce no tracked outputs (e.g. pure side-effect calls
    # with all-wildcard outputs) are appended at the end, preserving their
    # original relative order.
    for stmt in statements:
        if id(stmt) not in seen_stmts:
            sorted_stmts.append(stmt)
            seen_stmts.add(id(stmt))

    return sorted_stmts
