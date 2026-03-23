from __future__ import annotations

from typing import Callable

from kohakunode.ast.nodes import Branch, Jump, Literal, Namespace, Parallel, Statement, Switch
from kohakunode.engine.context import ExecutionContext
from kohakunode.errors import KirRuntimeError


def _find_namespace(name: str, statements: list[Statement]) -> Namespace:
    """Search *statements* for a Namespace whose name matches *name*.

    Raises KirRuntimeError if no matching Namespace is found.
    """
    for stmt in statements:
        if isinstance(stmt, Namespace) and stmt.name == name:
            return stmt
    raise KirRuntimeError(f"Namespace '{name}' not found in current scope")


def execute_branch(node: Branch, context: ExecutionContext) -> None:
    """Evaluate the branch condition and push a frame for the chosen namespace.

    The condition must already be stored as a bool in the variable store.
    Raises KirRuntimeError if the condition variable is not a bool.
    """
    from kohakunode.ast.nodes import Identifier

    # Resolve condition value from the variable store.
    if isinstance(node.condition, Identifier):
        condition_value = context.variables.get(node.condition.name)
    elif isinstance(node.condition, Literal):
        condition_value = node.condition.value
    else:
        raise KirRuntimeError(
            f"branch condition must be an Identifier or Literal, "
            f"got {type(node.condition).__name__}"
        )

    if not isinstance(condition_value, bool):
        raise KirRuntimeError(
            f"branch condition must be a bool, got {type(condition_value).__name__}"
        )

    target_label = node.true_label if condition_value else node.false_label
    current_statements = context.current_frame.statements
    target_ns = _find_namespace(target_label, current_statements)
    context.push_frame(target_ns.body, namespace_name=target_ns.name)


def execute_switch(node: Switch, context: ExecutionContext) -> None:
    """Evaluate the switch value and push a frame for the matching case namespace.

    Each case is a (Literal, label_name) tuple. The Literal's .value is compared
    against the resolved switch value. Falls through to default_label when present
    and no case matches. Raises KirRuntimeError when no match and no default exists.
    """
    from kohakunode.ast.nodes import Identifier

    # Resolve switch value from the variable store.
    if isinstance(node.value, Identifier):
        switch_value = context.variables.get(node.value.name)
    elif isinstance(node.value, Literal):
        switch_value = node.value.value
    else:
        raise KirRuntimeError(
            f"switch value must be an Identifier or Literal, "
            f"got {type(node.value).__name__}"
        )

    current_statements = context.current_frame.statements

    for case_expr, case_label in node.cases:
        if not isinstance(case_expr, Literal):
            raise KirRuntimeError(
                f"switch case expression must be a Literal, "
                f"got {type(case_expr).__name__}"
            )
        if case_expr.value == switch_value:
            target_ns = _find_namespace(case_label, current_statements)
            context.push_frame(target_ns.body, namespace_name=target_ns.name)
            return

    # No case matched — try default.
    if node.default_label is not None:
        target_ns = _find_namespace(node.default_label, current_statements)
        context.push_frame(target_ns.body, namespace_name=target_ns.name)
        return

    raise KirRuntimeError(
        f"switch: no case matched value {switch_value!r} and no default label is defined"
    )


def execute_jump(node: Jump, context: ExecutionContext) -> int:
    """Unconditionally jump to a target namespace.

    Searches the frame stack (top to bottom) for a frame whose statements
    contain the target namespace.  All frames *above* the containing frame are
    popped (cleaning up intermediate frames), and then the target namespace's
    body is pushed as a new frame.

    Returns the **index** of the frame that contained the target namespace.
    The interpreter uses this to decide whether to advance the containing
    frame (sibling jump) or leave it as-is (child-to-parent jump).

    Raises KirRuntimeError if the target namespace is not found anywhere in the
    frame stack.
    """
    frame_stack = context._frame_stack  # noqa: SLF001

    # Walk from the top of the stack down to the root frame.
    for idx in range(len(frame_stack) - 1, -1, -1):
        frame = frame_stack[idx]
        for stmt in frame.statements:
            if isinstance(stmt, Namespace) and stmt.name == node.target:
                # Pop all frames above the containing frame.
                while len(frame_stack) > idx + 1:
                    frame_stack.pop()
                # Push the target namespace body.
                context.push_frame(stmt.body, namespace_name=stmt.name)
                return idx

    raise KirRuntimeError(
        f"jump: target namespace '{node.target}' not found in any enclosing scope"
    )


def execute_parallel(
    node: Parallel,
    context: ExecutionContext,
    run_body: Callable[[list[Statement]], None],
) -> None:
    """Execute each listed namespace body in order, delegating to *run_body*.

    The *parallel* construct guarantees no ordering between the listed branches
    (semantically they are concurrent), but this runtime executes them sequentially
    in the listed order because actual concurrency is not required.

    *run_body* is a callback provided by the interpreter that accepts a list of
    statements and runs them to completion. This avoids a circular import between
    the interpreter and builtins modules.

    Raises KirRuntimeError if any listed label does not resolve to a namespace in
    the current frame's statements.
    """
    current_statements = context.current_frame.statements

    for label in node.labels:
        target_ns = _find_namespace(label, current_statements)
        run_body(target_ns.body)
