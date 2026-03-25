"""ComfyUI-style execution backend — faithful to ComfyUI's real architecture.

ComfyUI's execution model has these key concepts:
1. Output caching keyed by (node_id, input_signature_hash)
2. IS_CHANGED — a per-function fingerprint that forces re-execution
3. Per-node persistent state across runs
4. Execution tracking — shows which nodes were skipped vs executed
5. VALIDATE_INPUTS — pre-execution validation per node
6. ExecutionBlocker — a node can block downstream execution

This example implements all of these on top of KohakuNodeIR's ExecutionBackend.

Reference: ComfyUI/execution.py, ComfyUI/comfy_execution/caching.py
"""

import hashlib
import pickle
import random
import time
from dataclasses import dataclass, field
from typing import Any

from kohakunode import ExecutionBackend, Executor, NodeInvocation, Registry

# ---------------------------------------------------------------------------
# ExecutionBlocker — a node can return this to halt downstream
# ---------------------------------------------------------------------------


class ExecutionBlocker:
    """Returned by a node function to block downstream execution.

    In ComfyUI, this prevents dependent nodes from running.
    The message is reported to the user.
    """

    def __init__(self, message: str | None = None):
        self.message = message

    def __repr__(self) -> str:
        return f"ExecutionBlocker({self.message!r})"


# ---------------------------------------------------------------------------
# ComfyStyleBackend
# ---------------------------------------------------------------------------


@dataclass
class NodeCacheEntry:
    """Cached output for a single node execution."""

    input_hash: str
    is_changed_val: Any
    result: Any


class ComfyStyleBackend(ExecutionBackend):
    """Execution backend faithful to ComfyUI's real caching model.

    Key behaviors:
    - Cache keyed by (node_id, hash(inputs)) — same inputs = skip
    - IS_CHANGED: per-function fingerprint that invalidates cache
    - VALIDATE_INPUTS: pre-execution validation per function
    - ExecutionBlocker: nodes can block downstream execution
    - Per-node persistent state dicts
    - Execution log showing [CACHED] vs [EXECUTE] vs [BLOCKED]
    """

    def __init__(self) -> None:
        self._cache: dict[str, NodeCacheEntry] = {}
        self._node_state: dict[str, dict[str, Any]] = {}
        self._is_changed_fns: dict[str, Any] = {}
        self._validate_fns: dict[str, Any] = {}
        self._log: list[tuple[str, str, str]] = []  # (node_id, func, status)

    # -- Registration API --

    def register_is_changed(self, func_name: str, fn: Any) -> None:
        """Register an IS_CHANGED function.

        Called with the same kwargs as the node. If the return value
        differs from the previous call, the node re-executes even if
        inputs are unchanged. (Like ComfyUI's IS_CHANGED classmethod.)
        """
        self._is_changed_fns[func_name] = fn

    def register_validate_inputs(self, func_name: str, fn: Any) -> None:
        """Register a VALIDATE_INPUTS function.

        Called with the same kwargs before execution. Must return True
        for valid, or a string error message. (Like ComfyUI's
        VALIDATE_INPUTS classmethod.)
        """
        self._validate_fns[func_name] = fn

    def get_node_state(self, node_id: str) -> dict[str, Any]:
        """Return persistent state dict for a node."""
        return self._node_state.setdefault(node_id, {})

    # -- ExecutionBackend interface --

    def invoke(self, invocation: NodeInvocation) -> Any:
        node_id = invocation.node_id or invocation.spec.name
        func_name = invocation.spec.name
        input_hash = self._hash_inputs(invocation)

        # 1. Compute IS_CHANGED fingerprint
        is_changed_fn = self._is_changed_fns.get(func_name)
        is_changed_val = None
        if is_changed_fn is not None:
            is_changed_val = is_changed_fn(**invocation.call_kwargs)

        # 2. Check cache
        entry = self._cache.get(node_id)
        if entry is not None:
            input_match = entry.input_hash == input_hash
            is_changed_match = entry.is_changed_val == is_changed_val
            if input_match and is_changed_match:
                self._log.append((node_id, func_name, "CACHED"))
                return entry.result

        # 3. Validate inputs
        validate_fn = self._validate_fns.get(func_name)
        if validate_fn is not None:
            validation = validate_fn(**invocation.call_kwargs)
            if validation is not True:
                msg = validation if isinstance(validation, str) else "Validation failed"
                self._log.append((node_id, func_name, "INVALID"))
                raise ValueError(f"[{node_id}] {func_name}: {msg}")

        # 4. Execute
        result = invocation.spec.func(**invocation.call_kwargs)

        # 5. Handle ExecutionBlocker
        if isinstance(result, ExecutionBlocker):
            self._log.append((node_id, func_name, "BLOCKED"))
            if result.message:
                print(f"  [BLOCKED] {node_id}: {result.message}")
            return result

        # 6. Cache result
        self._cache[node_id] = NodeCacheEntry(
            input_hash=input_hash,
            is_changed_val=is_changed_val,
            result=result,
        )
        self._log.append((node_id, func_name, "EXECUTE"))
        return result

    def print_log(self, header: str = "") -> None:
        if header:
            print(f"\n{'=' * 60}")
            print(f"  {header}")
            print(f"{'=' * 60}")
        for node_id, func_name, status in self._log:
            match status:
                case "CACHED":
                    tag = "\033[32m[CACHED] \033[0m"
                case "EXECUTE":
                    tag = "\033[33m[EXECUTE]\033[0m"
                case "BLOCKED":
                    tag = "\033[31m[BLOCKED]\033[0m"
                case "INVALID":
                    tag = "\033[31m[INVALID]\033[0m"
                case _:
                    tag = f"[{status}]"
            print(f"  {tag} {func_name:20s} (node_id={node_id})")
        self._log.clear()

    def invalidate(self, node_id: str | None = None) -> None:
        """Clear cache for a specific node or all nodes."""
        if node_id is None:
            self._cache.clear()
        else:
            self._cache.pop(node_id, None)

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


# ===========================================================================
# Demo: Image processing pipeline
# ===========================================================================

# -- Simulated image processing nodes --


def load_image(path: str) -> dict:
    """Simulate loading an image (slow I/O)."""
    time.sleep(0.02)
    return {"path": path, "w": 1024, "h": 768, "data": f"pixels({path})"}


def resize(image: dict, width: int, height: int) -> dict:
    time.sleep(0.01)
    return {**image, "w": width, "h": height}


def blur(image: dict, radius: float) -> dict:
    time.sleep(0.01)
    return {**image, "blur": radius}


def random_seed() -> int:
    """Always produces a new value — IS_CHANGED forces re-execution."""
    return random.randint(0, 2**32 - 1)


def apply_noise(image: dict, seed: int) -> dict:
    time.sleep(0.01)
    return {**image, "noise_seed": seed}


def save_image(image: dict, path: str) -> str:
    time.sleep(0.01)
    return f"saved {image['w']}x{image['h']} to {path}"


def conditional_save(
    image: dict, path: str, should_save: bool
) -> str | ExecutionBlocker:
    """Only saves if should_save is True. Otherwise blocks downstream."""
    if not should_save:
        return ExecutionBlocker("Save disabled by user")
    time.sleep(0.01)
    return f"saved to {path}"


# -- Registry --

registry = Registry()
registry.register("LoadImage", load_image, output_names=["image"])
registry.register("Resize", resize, output_names=["image"])
registry.register("Blur", blur, output_names=["image"])
registry.register("RandomSeed", random_seed, output_names=["seed"])
registry.register("ApplyNoise", apply_noise, output_names=["image"])
registry.register("SaveImage", save_image, output_names=["status"])
registry.register("ConditionalSave", conditional_save, output_names=["status"])

# -- Backend setup --

backend = ComfyStyleBackend()

# RandomSeed: IS_CHANGED always returns a new value → always re-executes
backend.register_is_changed("RandomSeed", lambda: random.random())

# Resize: validate that dimensions are positive
backend.register_validate_inputs(
    "Resize",
    lambda image, width, height: (
        True if width > 0 and height > 0 else f"Invalid dimensions: {width}x{height}"
    ),
)

# -- KIR program --

KIR_SOURCE = """\
path = "photo.jpg"
width = 512
height = 512
radius = 2.5
out_path = "output.jpg"

@meta node_id="load"
(path)LoadImage(img)

@meta node_id="resize"
(img, width, height)Resize(img)

@meta node_id="blur"
(img, radius)Blur(img)

@meta node_id="seed"
()RandomSeed(seed)

@meta node_id="noise"
(img, seed)ApplyNoise(img)

@meta node_id="save"
(img, out_path)SaveImage(status)
"""

# -- Run twice to demonstrate caching --

executor = Executor(registry=registry, backend=backend, validate=False)

print("Run 1: All nodes execute (cold cache)")
store1 = executor.execute_source(KIR_SOURCE)
backend.print_log("Run 1")
print(f"  Result: {store1.get('status')}")

print("\nRun 2: Unchanged nodes cached, RandomSeed forces re-execution")
print("        (noise and save re-execute because their inputs changed)")
store2 = executor.execute_source(KIR_SOURCE)
backend.print_log("Run 2")
print(f"  Result: {store2.get('status')}")

# -- Demonstrate VALIDATE_INPUTS --

print("\nRun 3: Invalid resize dimensions (validation error)")
BAD_SOURCE = """\
path = "photo.jpg"
width = -1
height = 0

@meta node_id="load"
(path)LoadImage(img)

@meta node_id="resize"
(img, width, height)Resize(img)
"""

try:
    executor.execute_source(BAD_SOURCE)
except ValueError as e:
    print(f"  Caught: {e}")
    backend.print_log("Run 3")

# -- Show persistent node state --

print(f"\nNode state for 'seed': {backend.get_node_state('seed')}")
