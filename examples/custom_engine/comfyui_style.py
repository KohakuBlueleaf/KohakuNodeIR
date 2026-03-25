"""ComfyUI-style execution engine with caching and node state.

In ComfyUI, nodes can:
- Cache their outputs (skip if inputs unchanged)
- Have persistent state across executions
- Force re-execution via IS_CHANGED

This example shows how to build all three using ExecutionBackend.
"""

import hashlib
import pickle
import random
import time
from typing import Any

from kohakunode import ExecutionBackend, Executor, NodeInvocation, Registry


class ComfyStyleBackend(ExecutionBackend):
    """Execution backend inspired by ComfyUI's caching and state model.

    Features:
    - Output caching keyed on (node_id, input_hash)
    - Per-node persistent state dicts
    - IS_CHANGED functions that can force re-execution
    - Execution tracking (cached vs executed)
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, Any]] = {}  # node_id -> (input_hash, result)
        self._node_state: dict[str, dict[str, Any]] = {}  # node_id -> state dict
        self._is_changed_fns: dict[str, Any] = {}  # func_name -> callable
        self._execution_log: list[tuple[str, str, bool]] = (
            []
        )  # (node_id, func, cached?)

    def register_is_changed(self, func_name: str, fn: Any) -> None:
        """Register an IS_CHANGED function for a given function name.

        When set, the function is called with the same kwargs as the node.
        If it returns a different value than the last call, the node re-executes
        even if inputs are unchanged.
        """
        self._is_changed_fns[func_name] = fn

    def get_node_state(self, node_id: str) -> dict[str, Any]:
        """Return the persistent state dict for a node, creating if needed."""
        if node_id not in self._node_state:
            self._node_state[node_id] = {}
        return self._node_state[node_id]

    def invoke(self, invocation: NodeInvocation) -> Any:
        node_id = invocation.node_id or invocation.spec.name
        func_name = invocation.spec.name
        input_hash = self._hash_inputs(invocation)

        # Check IS_CHANGED
        is_changed_fn = self._is_changed_fns.get(func_name)
        force = False
        if is_changed_fn is not None:
            changed_val = is_changed_fn(**invocation.call_kwargs)
            state = self.get_node_state(node_id)
            if state.get("_is_changed_val") != changed_val:
                state["_is_changed_val"] = changed_val
                force = True

        # Check cache
        if not force and node_id in self._cache:
            cached_hash, cached_result = self._cache[node_id]
            if cached_hash == input_hash:
                self._execution_log.append((node_id, func_name, True))
                return cached_result

        # Execute
        result = invocation.spec.func(**invocation.call_kwargs)
        self._cache[node_id] = (input_hash, result)
        self._execution_log.append((node_id, func_name, False))
        return result

    def print_log(self, header: str = "") -> None:
        """Print execution log showing cached vs executed nodes."""
        if header:
            print(f"\n{'=' * 50}")
            print(f"  {header}")
            print(f"{'=' * 50}")
        for node_id, func_name, cached in self._execution_log:
            tag = "[CACHED]" if cached else "[EXECUTE]"
            print(f"  {tag:10s} {func_name}  (node_id={node_id})")
        self._execution_log.clear()

    @staticmethod
    def _hash_inputs(invocation: NodeInvocation) -> str:
        h = hashlib.sha256(invocation.spec.name.encode())
        for k in sorted(invocation.call_kwargs):
            h.update(k.encode())
            try:
                h.update(pickle.dumps(invocation.call_kwargs[k]))
            except (pickle.PicklingError, TypeError):
                h.update(str(id(invocation.call_kwargs[k])).encode())
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Define some image-processing nodes (simulated with dicts)
# ---------------------------------------------------------------------------


def load_image(path: str) -> dict:
    """Simulate loading an image from disk."""
    time.sleep(0.01)  # pretend I/O
    return {"type": "image", "path": path, "width": 1024, "height": 768, "data": "..."}


def resize(image: dict, width: int, height: int) -> dict:
    """Simulate resizing an image."""
    time.sleep(0.01)
    return {**image, "width": width, "height": height}


def blur(image: dict, radius: float) -> dict:
    """Simulate applying a Gaussian blur."""
    time.sleep(0.01)
    return {**image, "blur_radius": radius}


def save_image(image: dict, path: str) -> str:
    """Simulate saving an image to disk."""
    time.sleep(0.01)
    return f"saved to {path} ({image['width']}x{image['height']})"


def random_seed() -> int:
    """Generate a random seed -- should always re-execute."""
    return random.randint(0, 2**32 - 1)


def apply_noise(image: dict, seed: int) -> dict:
    """Simulate adding noise to an image using a seed."""
    time.sleep(0.01)
    return {**image, "noise_seed": seed}


# ---------------------------------------------------------------------------
# Set up registry
# ---------------------------------------------------------------------------

registry = Registry()
registry.register("LoadImage", load_image, output_names=["image"])
registry.register("Resize", resize, output_names=["image"])
registry.register("Blur", blur, output_names=["image"])
registry.register("SaveImage", save_image, output_names=["status"])
registry.register("RandomSeed", random_seed, output_names=["seed"])
registry.register("ApplyNoise", apply_noise, output_names=["image"])

# ---------------------------------------------------------------------------
# Set up backend with IS_CHANGED for RandomSeed
# ---------------------------------------------------------------------------

backend = ComfyStyleBackend()

# RandomSeed always returns a new value, so IS_CHANGED always differs.
backend.register_is_changed("RandomSeed", lambda: random.random())

# ---------------------------------------------------------------------------
# KIR program: image pipeline with a random noise step
# ---------------------------------------------------------------------------

KIR_SOURCE = """\
path = "photo.jpg"
width = 512
height = 512
radius = 2.5
out_path = "output.jpg"

@meta node_id="load1"
(path)LoadImage(img)

@meta node_id="resize1"
(img, width, height)Resize(img)

@meta node_id="blur1"
(img, radius)Blur(img)

@meta node_id="seed1"
()RandomSeed(seed)

@meta node_id="noise1"
(img, seed)ApplyNoise(img)

@meta node_id="save1"
(img, out_path)SaveImage(status)
"""

# ---------------------------------------------------------------------------
# Run the pipeline twice
# ---------------------------------------------------------------------------

executor = Executor(registry=registry, backend=backend, validate=False)

print("Run 1: everything executes")
store1 = executor.execute_source(KIR_SOURCE)
backend.print_log("Run 1 Results")
print(f"  Output: {store1.get('status')}")

print("\nRun 2: unchanged nodes are cached, RandomSeed forces re-execution")
store2 = executor.execute_source(KIR_SOURCE)
backend.print_log("Run 2 Results")
print(f"  Output: {store2.get('status')}")

# Show that node state persists
print("\nPersistent node state for 'seed1':")
print(f"  {backend.get_node_state('seed1')}")
