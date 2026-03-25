"""Example: StatefulBackend that gives nodes persistent state across runs."""

from typing import Any

from kohakunode import ExecutionBackend, Executor, NodeInvocation, Registry


class StatefulBackend(ExecutionBackend):
    """Each node_id gets a persistent state dict across runs."""

    def __init__(self):
        self._state: dict[str, dict] = {}  # node_id -> state dict

    def get_state(self, node_id: str) -> dict:
        return self._state.setdefault(node_id, {})

    def invoke(self, invocation: NodeInvocation) -> Any:
        # Inject node state into kwargs if the function accepts 'state'
        kwargs = dict(invocation.call_kwargs)
        if "state" in invocation.spec.input_names:
            nid = invocation.node_id or "anonymous"
            kwargs["state"] = self.get_state(nid)
        return invocation.spec.func(**kwargs)


# A counter node that remembers how many times it's been called
def counter(state):
    state["count"] = state.get("count", 0) + 1
    return state["count"]


registry = Registry()
registry.register("counter", counter, input_names=["state"], output_names=["count"])
registry.register("print_val", lambda x: print(f"  count = {x}"), output_names=[])

backend = StatefulBackend()
executor = Executor(registry=registry, backend=backend, validate=False)

source = """\
@meta node_id="c1"
()counter(n)
(n)print_val()
"""

print("Run 1:")
executor.execute_source(source)
print("Run 2:")
executor.execute_source(source)
print("Run 3:")
executor.execute_source(source)
