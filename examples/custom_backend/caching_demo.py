"""Example: CachingBackend skips re-execution when inputs are unchanged."""

from kohakunode import CachingBackend, Executor, Registry

call_count = {"add": 0}


def counted_add(a, b):
    call_count["add"] += 1
    return a + b


registry = Registry()
registry.register("add", counted_add, output_names=["result"])

backend = CachingBackend()
executor = Executor(registry=registry, backend=backend, validate=False)

# First run
store1 = executor.execute_source("x = 10\ny = 20\n(x, y)add(sum)")
print(f"Run 1: sum={store1.get('sum')}, add called {call_count['add']} time(s)")

# Second run with same inputs -- cached
store2 = executor.execute_source("x = 10\ny = 20\n(x, y)add(sum)")
print(f"Run 2: sum={store2.get('sum')}, add called {call_count['add']} time(s)")

# Invalidate and re-run
backend.invalidate()
store3 = executor.execute_source("x = 10\ny = 20\n(x, y)add(sum)")
print(
    f"Run 3 (after invalidate): sum={store3.get('sum')}, add called {call_count['add']} time(s)"
)
