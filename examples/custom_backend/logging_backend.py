"""Example: LoggingBackend that records all function invocations."""

import time
from typing import Any

from kohakunode import ExecutionBackend, Executor, NodeInvocation, Registry


class LoggingBackend(ExecutionBackend):
    def __init__(self):
        self.log: list[dict[str, Any]] = []

    def invoke(self, invocation: NodeInvocation) -> Any:
        start = time.perf_counter()
        result = invocation.spec.func(**invocation.call_kwargs)
        elapsed = time.perf_counter() - start
        self.log.append(
            {
                "func": invocation.spec.name,
                "args": invocation.call_kwargs,
                "result": result,
                "elapsed_ms": elapsed * 1000,
            }
        )
        return result


# Demo
registry = Registry()
registry.register("add", lambda a, b: a + b, output_names=["result"])
registry.register("multiply", lambda a, b: a * b, output_names=["result"])

if __name__ == "__main__":
    backend = LoggingBackend()
    store = Executor(registry=registry, backend=backend, validate=False).execute_source(
        """
x = 10
y = 20
(x, y)add(sum)
(sum, 3)multiply(product)
"""
    )

    print(f"product = {store.get('product')}")
    for entry in backend.log:
        print(
            f"  {entry['func']}({entry['args']}) = {entry['result']}"
            f" ({entry['elapsed_ms']:.2f}ms)"
        )
