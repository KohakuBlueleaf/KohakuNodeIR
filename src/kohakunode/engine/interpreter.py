from __future__ import annotations

from typing import Any

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
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
    Wildcard,
)
from kohakunode.engine.builtins import (
    execute_branch,
    execute_jump,
    execute_parallel,
    execute_switch,
)
from kohakunode.engine.context import ExecutionContext
from kohakunode.engine.registry import Registry
from kohakunode.errors import KirRuntimeError


class Interpreter:
    """Core interpreter that walks and executes a KohakuNodeIR AST."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.context = ExecutionContext()
        self.subgraphs: dict[str, SubgraphDef] = {}
        self._last_jump_containing_idx: int = -1

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, program: Program) -> None:
        """Execute a full KohakuNodeIR program."""
        # Collect subgraph definitions before execution begins.
        for stmt in program.body:
            if isinstance(stmt, SubgraphDef):
                self.subgraphs[stmt.name] = stmt

        # Push the program body as the initial frame and start the loop.
        self.context.push_frame(program.body)
        self._run_loop()

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Drive execution until all frames are exhausted."""
        while self.context.has_frames:
            stmt = self.context.current_statement

            # Frame exhausted — pop it and let the parent frame resume.
            if stmt is None:
                self.context.pop_frame()
                continue

            # Namespace blocks are skipped during sequential execution.
            if isinstance(stmt, Namespace):
                self.context.advance()
                continue

            # SubgraphDef blocks are already collected — skip them.
            if isinstance(stmt, SubgraphDef):
                self.context.advance()
                continue

            # ModeDecl is informational only — skip.
            if isinstance(stmt, ModeDecl):
                self.context.advance()
                continue

            # Capture the current frame *before* executing.  Builtins like
            # branch/switch/jump push new frames, which would make
            # context.current_frame point to the NEW frame.  We must advance
            # the frame that actually contains the statement we just ran.
            executing_frame = self.context.current_frame
            depth_before = len(self.context._frame_stack)  # noqa: SLF001

            self._execute_statement(stmt)

            depth_after = len(self.context._frame_stack)  # noqa: SLF001

            if isinstance(stmt, Jump):
                # execute_jump pops intermediate frames and returns the index
                # of the frame that contains the target namespace.
                # - Sibling jump (target in the same frame as the jump):
                #   advance the frame so we don't re-execute the jump.
                # - Child-to-parent jump (target in an ancestor frame):
                #   intermediate frames were already popped by execute_jump;
                #   the ancestor frame's position is already correct.
                jump_frame_idx = depth_before - 1
                containing_idx = self._last_jump_containing_idx
                if containing_idx == jump_frame_idx:
                    executing_frame.position += 1
            else:
                # Advance in the frame that owned this statement.  For
                # branch/switch this is the parent frame (not the newly
                # pushed one), so execution resumes correctly when the
                # child frame is later popped.
                executing_frame.position += 1

    # ------------------------------------------------------------------
    # Statement dispatch
    # ------------------------------------------------------------------

    def _execute_statement(self, stmt: Statement) -> None:
        """Dispatch a single statement to the appropriate handler."""
        if isinstance(stmt, Assignment):
            value = self._evaluate_expression(stmt.value)
            self.context.variables.set(stmt.target, value)

        elif isinstance(stmt, FuncCall):
            self._execute_func_call(stmt)

        elif isinstance(stmt, Branch):
            execute_branch(stmt, self.context)

        elif isinstance(stmt, Switch):
            execute_switch(stmt, self.context)

        elif isinstance(stmt, Jump):
            self._last_jump_containing_idx = execute_jump(stmt, self.context)

        elif isinstance(stmt, Parallel):
            execute_parallel(stmt, self.context, self._run_body)

        elif isinstance(stmt, Namespace):
            # Should never reach here — skipped in the main loop.
            pass

        elif isinstance(stmt, SubgraphDef):
            # Already collected; nothing to do.
            pass

        elif isinstance(stmt, ModeDecl):
            # Informational only.
            pass

        else:
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
            # KeywordArg should be handled by _evaluate_inputs, but if
            # encountered here, evaluate just the value part.
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
        # Check if the call targets a user-defined subgraph.
        if node.func_name in self.subgraphs:
            subgraph = self.subgraphs[node.func_name]
            results = self._execute_subgraph(subgraph, node.inputs)
            # Normalise: single-element list → bare value, multi → tuple.
            # This mirrors how regular Python functions return values.
            if len(results) == 1:
                result: Any = results[0]
            else:
                result = tuple(results)
            self._assign_outputs(node.outputs, result, node.func_name, node.line)
            return

        # Otherwise resolve from the registry.
        spec = self.registry.lookup(node.func_name)
        positional, keywords = self._evaluate_inputs(node.inputs)

        # Build the full keyword argument dict by mapping positional args
        # to the spec's declared input names, then overlaying explicit
        # keyword arguments.
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

        # Fill in defaults for any parameters not provided.
        for param_name in spec.input_names:
            if param_name not in call_kwargs:
                if param_name in spec.defaults:
                    call_kwargs[param_name] = spec.defaults[param_name]

        result = spec.func(**call_kwargs)

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
            # No outputs declared — discard the result.
            return

        if len(output_targets) == 1:
            target = output_targets[0]
            if not isinstance(target, Wildcard) and target != "_":
                self.context.variables.set(target, result)  # type: ignore[arg-type]
            return

        # Multiple outputs — result must be a tuple or list.
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
        """Call a user-defined subgraph like a function.

        1. Bind input arguments to the subgraph's parameters.
        2. Execute the subgraph body to completion.
        3. Collect and return output variable values.
        """
        positional, keywords = self._evaluate_inputs(inputs)

        # Bind positional args to parameter names.
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

        # Bind any remaining keyword arguments that weren't consumed above.
        for key, value in keywords.items():
            self.context.variables.set(key, value)

        # Execute the body synchronously.
        self._run_body(subgraph.body)

        # Collect output values.
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
    # Helper: run a body to completion
    # ------------------------------------------------------------------

    def _run_body(self, statements: list[Statement]) -> None:
        """Push a frame and run until that frame (and any it spawns) completes.

        This is the synchronous execution primitive used by ``execute_parallel``
        and ``_execute_subgraph``.  It pushes a new frame, records the target
        depth, and runs the loop until the stack shrinks back.
        """
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

            if isinstance(stmt, Namespace):
                self.context.advance()
                continue

            if isinstance(stmt, SubgraphDef):
                self.context.advance()
                continue

            if isinstance(stmt, ModeDecl):
                self.context.advance()
                continue

            executing_frame = self.context.current_frame
            depth_before = len(self.context._frame_stack)  # noqa: SLF001

            self._execute_statement(stmt)

            depth_after = len(self.context._frame_stack)  # noqa: SLF001

            if isinstance(stmt, Jump):
                jump_frame_idx = depth_before - 1
                containing_idx = self._last_jump_containing_idx
                if containing_idx == jump_frame_idx:
                    executing_frame.position += 1
            else:
                executing_frame.position += 1
