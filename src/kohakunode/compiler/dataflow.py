from __future__ import annotations

from kohakunode.ast.nodes import (
    Branch,
    DataflowBlock,
    Jump,
    Namespace,
    Parallel,
    Program,
    Statement,
    SubgraphDef,
    Switch,
)
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

        Handles two forms:

        1. **Whole-file dataflow** (``@mode dataflow``): all statements are
           topologically sorted and the mode flag is cleared.
        2. **Scoped dataflow blocks** (``@dataflow:``): each
           :class:`~kohakunode.ast.nodes.DataflowBlock` is sorted internally
           and its statements are inlined into the parent body.

        Parameters
        ----------
        program:
            The input program to transform.

        Returns
        -------
        Program
            A new :class:`~kohakunode.ast.nodes.Program` whose ``body`` is
            topologically sorted and whose ``mode`` is ``None``.  If
            ``program.mode`` is not ``"dataflow"`` and no
            :class:`~kohakunode.ast.nodes.DataflowBlock` nodes are present,
            the original program is returned unchanged.

        Raises
        ------
        KirCompilationError
            If any control-flow construct is found inside a whole-file
            dataflow program body.
        """
        # Handle @mode dataflow (whole-file) as before.
        if program.mode == "dataflow":
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

        # Handle scoped @dataflow: blocks.
        new_body = self._expand_dataflow_blocks(program.body)

        if new_body is program.body:
            # No DataflowBlock found anywhere — return unchanged.
            return program

        return Program(body=new_body, mode=program.mode)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _expand_dataflow_blocks(
        self, stmts: list[Statement]
    ) -> list[Statement]:
        """Replace :class:`DataflowBlock` nodes with their sorted contents.

        Returns the *same list object* when no DataflowBlock is found
        (used as a sentinel by the caller to detect the no-op case).
        """
        found = False
        new_body: list[Statement] = []

        for stmt in stmts:
            if isinstance(stmt, DataflowBlock):
                found = True
                block_prog = Program(body=stmt.body)
                graph = DependencyGraphBuilder().build(block_prog)
                sorted_stmts = topological_sort(graph, stmt.body)
                new_body.extend(sorted_stmts)
            elif isinstance(stmt, Namespace):
                inner = self._expand_dataflow_blocks(stmt.body)
                if inner is not stmt.body:
                    found = True
                    new_body.append(
                        Namespace(name=stmt.name, body=inner, line=stmt.line)
                    )
                else:
                    new_body.append(stmt)
            elif isinstance(stmt, SubgraphDef):
                inner = self._expand_dataflow_blocks(stmt.body)
                if inner is not stmt.body:
                    found = True
                    new_body.append(
                        SubgraphDef(
                            name=stmt.name,
                            params=stmt.params,
                            outputs=stmt.outputs,
                            body=inner,
                            line=stmt.line,
                        )
                    )
                else:
                    new_body.append(stmt)
            else:
                new_body.append(stmt)

        if not found:
            return stmts
        return new_body
