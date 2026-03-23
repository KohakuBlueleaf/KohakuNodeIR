from __future__ import annotations

from kohakunode.ast.nodes import Branch, Jump, Namespace, Parallel, Program, Switch
from kohakunode.compiler.passes import DependencyGraphBuilder, IRPass, topological_sort
from kohakunode.errors import KirCompilationError

# ---------------------------------------------------------------------------
# Control-flow node types that are illegal in dataflow mode
# ---------------------------------------------------------------------------

_CONTROL_FLOW_TYPES = (Branch, Jump, Namespace, Parallel, Switch)

# ---------------------------------------------------------------------------
# DataflowCompiler
# ---------------------------------------------------------------------------


class DataflowCompiler(IRPass):
    """Compiles a dataflow-mode :class:`~kohakunode.ast.nodes.Program` into a
    sequentially-ordered one by topologically sorting its statements according
    to their data dependencies.

    If the program is not in dataflow mode the pass is a no-op.  If the
    program contains control-flow constructs (Namespace, Branch, Switch, Jump,
    or Parallel) a :class:`~kohakunode.errors.KirCompilationError` is raised,
    because those constructs are incompatible with pure dataflow ordering.
    """

    @property
    def name(self) -> str:
        return "dataflow_to_sequential"

    def transform(self, program: Program) -> Program:
        """Reorder *program* statements by data dependency and clear the mode flag.

        Parameters
        ----------
        program:
            The input program to transform.

        Returns
        -------
        Program
            A new :class:`~kohakunode.ast.nodes.Program` whose ``body`` is
            topologically sorted and whose ``mode`` is ``None``.  If
            ``program.mode`` is not ``"dataflow"`` the original program is
            returned unchanged.

        Raises
        ------
        KirCompilationError
            If any control-flow construct is found inside the program body.
        """
        if program.mode != "dataflow":
            return program

        # Validate: no control-flow constructs allowed in dataflow mode.
        for stmt in program.body:
            if isinstance(stmt, _CONTROL_FLOW_TYPES):
                raise KirCompilationError(
                    f"Control-flow construct '{type(stmt).__name__}' is not "
                    f"allowed in dataflow mode and cannot be compiled to "
                    f"sequential IR. Remove or lower all control-flow nodes "
                    f"before running the dataflow compiler."
                )

        graph = DependencyGraphBuilder().build(program)
        sorted_statements = topological_sort(graph, program.body)

        return Program(body=sorted_statements, mode=None)
