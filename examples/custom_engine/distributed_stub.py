"""Conceptual: distributed execution backend.

Shows the pattern for dispatching function calls to remote workers.
Uses a mock "remote call" that just runs locally, but demonstrates
the architecture for real distributed execution.
"""

import json
import time
from typing import Any

from kohakunode import ExecutionBackend, Executor, NodeInvocation, Registry


class DistributedBackend(ExecutionBackend):
    """Backend that dispatches function calls to remote workers.

    In a real system, ``_remote_call`` would send a request over HTTP/gRPC
    to a worker process. Here we simulate it locally while demonstrating
    the serialization and dispatch pattern.
    """

    def __init__(self) -> None:
        # Map function names to worker URLs.
        self.workers: dict[str, str] = {}
        self._dispatch_log: list[dict[str, Any]] = []

    def assign_worker(self, func_name: str, worker_url: str) -> None:
        """Route a function to a specific worker."""
        self.workers[func_name] = worker_url

    def invoke(self, invocation: NodeInvocation) -> Any:
        worker_url = self.workers.get(invocation.spec.name, "local://default")

        # Serialize the invocation to JSON (what you'd send over the wire)
        payload = self._serialize(invocation)

        # "Send" to worker and get result back
        result = self._remote_call(worker_url, payload, invocation)
        return result

    def _serialize(self, invocation: NodeInvocation) -> str:
        """Serialize an invocation to JSON for wire transport."""
        payload = {
            "func_name": invocation.spec.name,
            "kwargs": {},
            "node_id": invocation.node_id,
        }
        for k, v in invocation.call_kwargs.items():
            try:
                json.dumps(v)
                payload["kwargs"][k] = v
            except (TypeError, ValueError):
                payload["kwargs"][k] = f"<non-serializable: {type(v).__name__}>"
        return json.dumps(payload, indent=2)

    def _remote_call(
        self, worker_url: str, payload: str, invocation: NodeInvocation
    ) -> Any:
        """Simulate a remote call. In production, this would be HTTP/gRPC."""
        start = time.perf_counter()

        # Log the dispatch
        self._dispatch_log.append(
            {
                "worker": worker_url,
                "func": invocation.spec.name,
                "node_id": invocation.node_id,
                "payload_size": len(payload),
            }
        )

        # Actually run locally (the mock part)
        result = invocation.spec.func(**invocation.call_kwargs)
        elapsed = time.perf_counter() - start

        print(
            f"  [{worker_url}] {invocation.spec.name}"
            f"  -> dispatched ({len(payload)} bytes, {elapsed*1000:.1f}ms)"
        )
        return result

    def print_dispatch_summary(self) -> None:
        """Print a summary of all dispatched calls."""
        print(f"\n{'=' * 55}")
        print("  Dispatch Summary")
        print(f"{'=' * 55}")
        by_worker: dict[str, int] = {}
        for entry in self._dispatch_log:
            w = entry["worker"]
            by_worker[w] = by_worker.get(w, 0) + 1
        for worker, count in sorted(by_worker.items()):
            print(f"  {worker}: {count} call(s)")
        print(f"  Total: {len(self._dispatch_log)} call(s)")


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def fetch_data(url: str) -> dict:
    """Simulate fetching data from a URL."""
    time.sleep(0.01)
    return {"source": url, "rows": 1000}


def filter_rows(data: dict, column: str, value: str) -> dict:
    """Simulate filtering rows."""
    time.sleep(0.01)
    return {**data, "filter": f"{column}={value}", "rows": data["rows"] // 2}


def aggregate(data: dict, func: str) -> dict:
    """Simulate aggregation."""
    time.sleep(0.01)
    return {"result": 42.0, "agg_func": func, "input_rows": data["rows"]}


def format_report(data: dict, title: str) -> str:
    """Format a simple report string."""
    return f"Report: {title} | {data['agg_func']}={data['result']} ({data['input_rows']} rows)"


# ---------------------------------------------------------------------------
# Set up registry and backend
# ---------------------------------------------------------------------------

registry = Registry()
registry.register("FetchData", fetch_data, output_names=["data"])
registry.register("FilterRows", filter_rows, output_names=["data"])
registry.register("Aggregate", aggregate, output_names=["data"])
registry.register("FormatReport", format_report, output_names=["report"])

backend = DistributedBackend()
# Route heavy computation to different "workers"
backend.assign_worker("FetchData", "http://worker-io:8080")
backend.assign_worker("FilterRows", "http://worker-compute:8080")
backend.assign_worker("Aggregate", "http://worker-compute:8080")
# FormatReport stays on local://default (lightweight)

# ---------------------------------------------------------------------------
# KIR program
# ---------------------------------------------------------------------------

KIR_SOURCE = """\
url = "https://data.example.com/sales.csv"
col = "region"
val = "US"
agg = "mean"
title = "US Sales Report"

@meta node_id="fetch1"
(url)FetchData(data)

@meta node_id="filter1"
(data, col, val)FilterRows(data)

@meta node_id="agg1"
(data, agg)Aggregate(stats)

@meta node_id="report1"
(stats, title)FormatReport(report)
"""

print("Distributed execution demo")
print("-" * 55)
store = Executor(registry=registry, backend=backend, validate=False).execute_source(
    KIR_SOURCE
)

print(f"\n  Final report: {store.get('report')}")
backend.print_dispatch_summary()

# Show what the serialized payload looks like
print(f"\n{'=' * 55}")
print("  Example serialized payload (what goes over the wire):")
print(f"{'=' * 55}")
from kohakunode import NodeInvocation  # noqa: E402

sample = NodeInvocation(
    spec=registry.lookup("FetchData"),
    call_kwargs={"url": "https://data.example.com/sales.csv"},
    node=None,  # type: ignore[arg-type]
    metadata={"node_id": "fetch1"},
)
print(backend._serialize(sample))
