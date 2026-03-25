"""Pipeline profiler: measures execution time per node.

Useful for finding bottlenecks in large KIR pipelines.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Any

from kohakunode import ExecutionBackend, Executor, NodeInvocation, Registry


@dataclass
class NodeTiming:
    """Accumulated timing for a single node invocation."""

    node_id: str
    func_name: str
    calls: int = 0
    total_ms: float = 0.0
    _start: float = field(default=0.0, repr=False)


class ProfilingBackend(ExecutionBackend):
    """Backend that profiles every node execution.

    Uses on_node_enter/on_node_exit hooks for timing. After execution,
    call print_report() to see a per-node breakdown.
    """

    def __init__(self) -> None:
        self._timings: dict[str, NodeTiming] = {}  # node_id -> timing
        self._func_totals: dict[str, float] = {}  # func_name -> total_ms

    def invoke(self, invocation: NodeInvocation) -> Any:
        return invocation.spec.func(**invocation.call_kwargs)

    def on_node_enter(self, invocation: NodeInvocation) -> None:
        node_id = invocation.node_id or f"anon_{id(invocation.node)}"
        if node_id not in self._timings:
            self._timings[node_id] = NodeTiming(
                node_id=node_id, func_name=invocation.spec.name
            )
        self._timings[node_id]._start = time.perf_counter()

    def on_node_exit(
        self, invocation: NodeInvocation, result: Any, error: Exception | None
    ) -> None:
        node_id = invocation.node_id or f"anon_{id(invocation.node)}"
        timing = self._timings.get(node_id)
        if timing is None:
            return
        elapsed_ms = (time.perf_counter() - timing._start) * 1000
        timing.calls += 1
        timing.total_ms += elapsed_ms

        fname = invocation.spec.name
        self._func_totals[fname] = self._func_totals.get(fname, 0.0) + elapsed_ms

    def print_report(self) -> None:
        """Print a formatted profiling report."""
        total = sum(t.total_ms for t in self._timings.values())
        if total == 0:
            print("  No profiling data collected.")
            return

        print(f"\n{'=' * 70}")
        print("  Pipeline Profiling Report")
        print(f"{'=' * 70}")

        # Per-node table
        header = f"  {'Node ID':<16s} {'Function':<16s} {'Calls':>5s} {'Time (ms)':>10s} {'%':>6s}"
        print(header)
        print(f"  {'-' * 16} {'-' * 16} {'-' * 5} {'-' * 10} {'-' * 6}")

        for timing in sorted(self._timings.values(), key=lambda t: -t.total_ms):
            pct = (timing.total_ms / total) * 100
            print(
                f"  {timing.node_id:<16s} {timing.func_name:<16s}"
                f" {timing.calls:>5d} {timing.total_ms:>10.2f} {pct:>5.1f}%"
            )

        print(f"  {'-' * 16} {'-' * 16} {'-' * 5} {'-' * 10} {'-' * 6}")
        print(f"  {'TOTAL':<16s} {'':<16s} {'':<5s} {total:>10.2f} {'100.0%':>6s}")

        # Per-function summary
        print(f"\n  {'Function Summary':}")
        print(f"  {'-' * 40}")
        for fname, fms in sorted(self._func_totals.items(), key=lambda x: -x[1]):
            pct = (fms / total) * 100
            print(f"  {fname:<20s} {fms:>10.2f} ms  ({pct:>5.1f}%)")


# ---------------------------------------------------------------------------
# Define a medium-size pipeline (12 nodes) with varying costs
# ---------------------------------------------------------------------------


def _make_sleepy(name: str, sleep_ms: float):
    """Create a function that sleeps for a given duration."""

    def fn(**kwargs):
        time.sleep(sleep_ms / 1000)
        return {**kwargs, "_step": name}

    return fn


def _make_transform(name: str, sleep_ms: float):
    """Create a transform node that takes data in and passes it through."""

    def fn(data, **kwargs):
        time.sleep(sleep_ms / 1000)
        return {**data, **kwargs, "_step": name}

    return fn


def load_dataset(path: str) -> dict:
    """Simulate loading a large dataset (slow I/O)."""
    time.sleep(0.05)
    return {"path": path, "rows": 100000}


def validate_schema(data: dict) -> dict:
    """Validate data schema (fast)."""
    time.sleep(0.002)
    return {**data, "valid": True}


def clean_nulls(data: dict) -> dict:
    """Remove null values (moderate)."""
    time.sleep(0.015)
    return {**data, "nulls_removed": True}


def normalize(data: dict) -> dict:
    """Normalize numeric columns (moderate)."""
    time.sleep(0.02)
    return {**data, "normalized": True}


def feature_engineer(data: dict) -> dict:
    """Create derived features (slow, CPU-bound)."""
    time.sleep(0.04)
    return {**data, "features": 50}


def split_data(data: dict, ratio: float) -> tuple:
    """Split into train/test (fast)."""
    time.sleep(0.003)
    train_rows = int(data["rows"] * ratio)
    test_rows = data["rows"] - train_rows
    return (
        {**data, "rows": train_rows, "split": "train"},
        {**data, "rows": test_rows, "split": "test"},
    )


def train_model(data: dict) -> dict:
    """Train a model (very slow)."""
    time.sleep(0.08)
    return {"model": "trained", "accuracy": 0.95, "train_rows": data["rows"]}


def evaluate_model(model: dict, data: dict) -> dict:
    """Evaluate model on test data (moderate)."""
    time.sleep(0.025)
    return {"accuracy": model["accuracy"], "test_rows": data["rows"]}


def generate_report(metrics: dict) -> str:
    """Generate a text report (fast)."""
    time.sleep(0.002)
    return f"accuracy={metrics['accuracy']}, test_rows={metrics['test_rows']}"


def save_model(model: dict, path: str) -> str:
    """Save model to disk (moderate I/O)."""
    time.sleep(0.02)
    return f"saved to {path}"


def log_experiment(report: str, model_path: str) -> str:
    """Log experiment results (fast)."""
    time.sleep(0.002)
    return f"logged: {report} | {model_path}"


# ---------------------------------------------------------------------------
# Set up registry
# ---------------------------------------------------------------------------

registry = Registry()
registry.register("LoadDataset", load_dataset, output_names=["data"])
registry.register("ValidateSchema", validate_schema, output_names=["data"])
registry.register("CleanNulls", clean_nulls, output_names=["data"])
registry.register("Normalize", normalize, output_names=["data"])
registry.register("FeatureEngineer", feature_engineer, output_names=["data"])
registry.register("SplitData", split_data, output_names=["train", "test"])
registry.register("TrainModel", train_model, output_names=["model"])
registry.register("EvaluateModel", evaluate_model, output_names=["metrics"])
registry.register("GenerateReport", generate_report, output_names=["report"])
registry.register("SaveModel", save_model, output_names=["path"])
registry.register("LogExperiment", log_experiment, output_names=["log_entry"])

# ---------------------------------------------------------------------------
# KIR program: ML pipeline (12 nodes)
# ---------------------------------------------------------------------------

KIR_SOURCE = """\
dataset_path = "data/sales.parquet"
split_ratio = 0.8
model_path = "models/sales_v1.pkl"

@meta node_id="load"
(dataset_path)LoadDataset(data)

@meta node_id="validate"
(data)ValidateSchema(data)

@meta node_id="clean"
(data)CleanNulls(data)

@meta node_id="normalize"
(data)Normalize(data)

@meta node_id="features"
(data)FeatureEngineer(data)

@meta node_id="split"
(data, split_ratio)SplitData(train_data, test_data)

@meta node_id="train"
(train_data)TrainModel(model)

@meta node_id="evaluate"
(model, test_data)EvaluateModel(metrics)

@meta node_id="report"
(metrics)GenerateReport(report)

@meta node_id="save"
(model, model_path)SaveModel(saved_path)

@meta node_id="log"
(report, saved_path)LogExperiment(log_entry)
"""

# ---------------------------------------------------------------------------
# Run with profiling
# ---------------------------------------------------------------------------

backend = ProfilingBackend()
store = Executor(registry=registry, backend=backend, validate=False).execute_source(
    KIR_SOURCE
)

print(f"Pipeline complete: {store.get('log_entry')}")
backend.print_report()
