from typing import Any

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    Expression,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    Literal,
    ModeDecl,
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
from kohakunode.engine.backend import DefaultBackend, ExecutionBackend, NodeInvocation
from kohakunode.engine.builtins import (
    execute_branch,
    execute_jump,
    execute_parallel,
    execute_switch,
)
from kohakunode.engine.context import ExecutionContext
from kohakunode.engine.registry import Registry
from kohakunode.errors import KirRuntimeError

# Statement types that are skipped during sequential execution.
_SKIP_TYPES = (Namespace, SubgraphDef, ModeDecl)


def _extract_metadata(node: FuncCall) -> dict[str, Any]:
    """Merge all @meta annotations on a FuncCall into a single dict."""
    if not node.metadata:
        return {}
    merged: dict[str, Any] = {}
    for meta in node.metadata:
        merged.update(meta.data)
    return merged


class Interpreter:
    """Core interpreter that walks and executes a KohakuNodeIR AST."""

    def __init__(
        self, registry: Registry, backend: ExecutionBackend | None = None
    ) -> None:
        self.registry = registry
        self.backend = backend if backend is not None else DefaultBackend()
        self.context = ExecutionContext()
        self.subgraphs: dict[str, SubgraphDef] = {}
        self._last_jump_containing_idx: int = -1

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, program: Program) -> None:
        """Execute a full KohakuNodeIR program."""
        for stmt in program.body:
            if isinstance(stmt, SubgraphDef):
                self.subgraphs[stmt.name] = stmt

        self.context.push_frame(program.body)
        self._run_loop()

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Drive execution until all frames are exhausted."""
        while self.context.has_frames:
            stmt = self.context.current_statement

            if stmt is None:
                self.context.pop_frame()
                continue

            if isinstance(stmt, _SKIP_TYPES):
                self.context.advance()
                continue

            self._step(stmt)

    # ------------------------------------------------------------------
    # Single-statement execution step (shared by loop and run_body)
    # ------------------------------------------------------------------

    def _step(self, stmt: Statement) -> None:
        """Execute one statement and advance the correct frame."""
        executing_frame = self.context.current_frame
        depth_before = len(self.context._frame_stack)  # noqa: SLF001

        self._execute_statement(stmt)

        if isinstance(stmt, Jump):
            jump_frame_idx = depth_before - 1
            if self._last_jump_containing_idx == jump_frame_idx:
                executing_frame.position += 1
        else:
            executing_frame.position += 1

    # ------------------------------------------------------------------
    # Statement dispatch
    # ------------------------------------------------------------------

    def _execute_statement(self, stmt: Statement) -> None:
        """Dispatch a single statement to the appropriate handler."""
        match stmt:
            case Assignment():
                value = self._evaluate_expression(stmt.value)
                self.context.variables.set(stmt.target, value)
            case FuncCall():
                self._execute_func_call(stmt)
            case Branch():
                execute_branch(stmt, self.context)
            case Switch():
                execute_switch(stmt, self.context)
            case Jump():
                self._last_jump_containing_idx = execute_jump(stmt, self.context)
            case Parallel():
                execute_parallel(stmt, self.context, self._run_body)
            case Namespace():
                pass
            case SubgraphDef():
                pass
            case DataflowBlock():
                self._run_body(stmt.body)
            case ModeDecl():
                pass
            case TryExcept():
                self._execute_try_except(stmt)
            case TypeHintBlock():
                pass
            case _:
                raise KirRuntimeError(
                    f"Unknown statement type: {type(stmt).__name__}",
                    line=stmt.line,
                )

    # ------------------------------------------------------------------
    # Expression evaluation
    # ------------------------------------------------------------------

    def _evaluate_expression(self, expr: Expression) -> Any:
        """Evaluate an expression and return its Python value."""
        if isinstance(expr, Identifier):
            return self.context.variables.get(expr.name)

        if isinstance(expr, Literal):
            return expr.value

        if isinstance(expr, KeywordArg):
            return self._evaluate_expression(expr.value)

        raise KirRuntimeError(
            f"Cannot evaluate expression of type {type(expr).__name__}",
            line=expr.line,
        )

    def _evaluate_inputs(
        self, inputs: list[Expression]
    ) -> tuple[list[Any], dict[str, Any]]:
        """Separate positional and keyword arguments and evaluate them.

        Returns (positional_values, keyword_dict).
        """
        positional: list[Any] = []
        keywords: dict[str, Any] = {}

        for inp in inputs:
            if isinstance(inp, KeywordArg):
                keywords[inp.name] = self._evaluate_expression(inp.value)
            else:
                positional.append(self._evaluate_expression(inp))

        return positional, keywords

    # ------------------------------------------------------------------
    # Function call execution
    # ------------------------------------------------------------------

    def _execute_func_call(self, node: FuncCall) -> None:
        """Execute a FuncCall statement."""
        if node.func_name in self.subgraphs:
            subgraph = self.subgraphs[node.func_name]
            results = self._execute_subgraph(subgraph, node.inputs)
            result: Any = results[0] if len(results) == 1 else tuple(results)
            self._assign_outputs(node.outputs, result, node.func_name, node.line)
            return

        spec = self.registry.lookup(node.func_name)
        positional, keywords = self._evaluate_inputs(node.inputs)

        call_kwargs: dict[str, Any] = {}
        for idx, value in enumerate(positional):
            if idx < len(spec.input_names):
                call_kwargs[spec.input_names[idx]] = value
            else:
                raise KirRuntimeError(
                    f"Too many positional arguments for '{node.func_name}': "
                    f"expected at most {len(spec.input_names)}, "
                    f"got {len(positional)}",
                    line=node.line,
                    function_name=node.func_name,
                )

        call_kwargs.update(keywords)

        for param_name in spec.input_names:
            if param_name not in call_kwargs and param_name in spec.defaults:
                call_kwargs[param_name] = spec.defaults[param_name]

        # Build invocation
        invocation = NodeInvocation(
            spec=spec,
            call_kwargs=call_kwargs,
            node=node,
            metadata=_extract_metadata(node),
        )

        # Delegate to backend with lifecycle hooks
        self.backend.on_node_enter(invocation)
        result = None
        error = None
        try:
            result = self.backend.invoke(invocation)
        except Exception as exc:
            error = exc
            raise
        finally:
            self.backend.on_node_exit(invocation, result, error)

        self._assign_outputs(node.outputs, result, node.func_name, node.line)

    def _assign_outputs(
        self,
        output_targets: list[str | Wildcard],
        result: Any,
        func_name: str,
        line: int | None,
    ) -> None:
        """Assign a function's return value(s) to the declared output targets."""
        if not output_targets:
            return

        if len(output_targets) == 1:
            target = output_targets[0]
            if not isinstance(target, Wildcard) and target != "_":
                self.context.variables.set(target, result)  # type: ignore[arg-type]
            return

        if isinstance(result, (tuple, list)):
            if len(result) != len(output_targets):
                raise KirRuntimeError(
                    f"Output count mismatch for '{func_name}': "
                    f"function returned {len(result)} values, "
                    f"but {len(output_targets)} outputs declared",
                    line=line,
                    function_name=func_name,
                )
            for target, value in zip(output_targets, result):
                if isinstance(target, Wildcard) or target == "_":
                    continue
                self.context.variables.set(target, value)  # type: ignore[arg-type]
        else:
            raise KirRuntimeError(
                f"Output count mismatch for '{func_name}': "
                f"expected {len(output_targets)} return values "
                f"but function returned a single value",
                line=line,
                function_name=func_name,
            )

    # ------------------------------------------------------------------
    # Subgraph execution
    # ------------------------------------------------------------------

    def _execute_subgraph(
        self, subgraph: SubgraphDef, inputs: list[Expression]
    ) -> list[Any]:
        """Call a user-defined subgraph like a function."""
        positional, keywords = self._evaluate_inputs(inputs)

        for idx, param in enumerate(subgraph.params):
            if idx < len(positional):
                self.context.variables.set(param.name, positional[idx])
            elif param.name in keywords:
                self.context.variables.set(param.name, keywords.pop(param.name))
            elif param.default is not None:
                self.context.variables.set(
                    param.name, self._evaluate_expression(param.default)
                )
            else:
                raise KirRuntimeError(
                    f"Missing argument '{param.name}' for subgraph '{subgraph.name}'",
                    function_name=subgraph.name,
                )

        for key, value in keywords.items():
            self.context.variables.set(key, value)

        self._run_body(subgraph.body)

        results: list[Any] = []
        for output_name in subgraph.outputs:
            if self.context.variables.has(output_name):
                results.append(self.context.variables.get(output_name))
            else:
                raise KirRuntimeError(
                    f"Subgraph '{subgraph.name}' output variable "
                    f"'{output_name}' is not defined after execution",
                    function_name=subgraph.name,
                )

        return results

    # ------------------------------------------------------------------
    # Try/except execution
    # ------------------------------------------------------------------

    def _execute_try_except(self, stmt: TryExcept) -> None:
        """Execute a @try/@except block, catching any Python exception."""
        try:
            for s in stmt.try_body:
                self._execute_statement(s)
        except Exception:
            for s in stmt.except_body:
                self._execute_statement(s)

    # ------------------------------------------------------------------
    # Helper: run a body to completion
    # ------------------------------------------------------------------

    def _run_body(self, statements: list[Statement]) -> None:
        """Push a frame and run until that frame (and any it spawns) completes."""
        target_depth = len(self.context._frame_stack)  # noqa: SLF001
        self.context.push_frame(statements)
        while (
            self.context.has_frames
            and len(self.context._frame_stack) > target_depth  # noqa: SLF001
        ):
            stmt = self.context.current_statement

            if stmt is None:
                self.context.pop_frame()
                continue

            if isinstance(stmt, _SKIP_TYPES):
                self.context.advance()
                continue

            self._step(stmt)
