"""The sequential reference interpreter (semantics.md).

Runs any program, before or after any optimization pass. Control is a program counter ``(block, index)``; where
a block ends is decided by what contains it, statically:

- a namespace entered by ``each`` or ``collect`` returns to its owner;
- a ``parallel`` arm continues with the next arm, the last one after the ``parallel``;
- any other namespace continues after its own definition;
- `@dataflow:` and `@try` bodies continue after their statement;
- the scope's own body ends the run.
"""

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from kohakunode.errors import EventDeliveryError, KirRuntimeError, NodeFailure
from kohakunode.events import Event
from kohakunode.flow.order import sort_dataflow
from kohakunode.sig.env import NodeEnv, Resolved
from kohakunode.sig.std import is_standard_emit
from kohakunode.syntax.ast import (
    Assign,
    Branch,
    Call,
    Collect,
    Dataflow,
    Def,
    Each,
    Expr,
    Jump,
    Literal,
    Namespace,
    Parallel,
    Program,
    Stmt,
    Switch,
    Try,
    TypeHints,
)

# hook(node_name, inputs, call) -> outputs; ``call()`` runs the node itself.
CallHook = Callable[[str, dict, Callable[[], Any]], Any]

_VERSION = re.compile(r"__\d+$")


@dataclass
class _Pos:
    block: list[Stmt]
    index: int


@dataclass
class _Scope:
    values: dict[str, Any] = field(default_factory=dict)
    order: dict[str, int] = field(default_factory=dict)  # name -> write sequence number
    tick: int = 0

    def set(self, name: str, value: Any) -> None:
        self.values[name] = value
        self.tick += 1
        self.order[name] = self.tick


class Interpreter:
    def __init__(
        self,
        program: Program,
        env: NodeEnv,
        nodes: dict[str, Callable] | None = None,
        hook: CallHook | None = None,
        step_budget: int | None = None,
        *,
        events: Callable[[Event], None] | None = None,
    ):
        self.program = copy.deepcopy(program)
        self.env = env
        self.nodes = nodes or {}
        self.hook = hook
        self.events: list[Event] = []
        self._event_callback = events
        self.steps = 0
        self.step_budget = step_budget
        sort_dataflow(self.program, self._is_ordered)
        self.parent: dict[int, tuple[list[Stmt], int, Stmt]] = {}
        self._index(self.program.body)
        self.defs = {s.name: s for s in _all(self.program.body) if isinstance(s, Def)}

    # ------------------------------------------------------------ structure
    def _is_ordered(self, s: Stmt) -> bool:
        if isinstance(s, Call):
            r = self.env.resolve(s.name)
            return isinstance(r, Resolved) and r.signature.ordered
        return False

    def _index(self, block: list[Stmt]) -> None:
        for i, s in enumerate(block):
            for body in _bodies(s):
                self.parent[id(body)] = (block, i, s)
                self._index(body)

    def _namespace(
        self, block: list[Stmt], label: str, search_up: bool
    ) -> tuple[list[Stmt], Namespace]:
        while True:
            for s in block:
                if isinstance(s, Namespace) and s.label == label:
                    return block, s
            if (
                not search_up
                or id(block) not in self.parent
                or isinstance(self.parent[id(block)][2], Def)
            ):
                raise KirRuntimeError(f"namespace `{label}` not found")
            block = self.parent[id(block)][0]

    def _owner(self, ns: Namespace, block: list[Stmt]) -> tuple[Stmt, int] | None:
        for i, s in enumerate(block):
            if isinstance(s, (Each, Collect)) and s.label == ns.label:
                return s, i
            if isinstance(s, Parallel) and ns.label in s.labels:
                return s, i
        return None

    # ------------------------------------------------------------ running
    def run(self) -> dict[str, Any]:
        """Run the top level; return its final values (names, or versions once versioned)."""
        self.events = []
        self.scope = _Scope()
        self._run_block(self.program.body)
        return dict(self.scope.values)

    def source_values(self) -> dict[str, Any]:
        """Final value of every source-level name: once versioned, the version written last."""
        best: dict[str, tuple[int, Any]] = {}
        for name, value in self.scope.values.items():
            src = _VERSION.sub("", name)
            if "__" in src:
                continue
            seq = self.scope.order[name]
            if src not in best or seq > best[src][0]:
                best[src] = (seq, value)
        return {k: v for k, (_, v) in sorted(best.items())}

    def _run_block(self, root: list[Stmt]) -> None:
        pos = _Pos(root, 0)
        each_state: dict[int, tuple[list, int]] = {}
        resume_each: set[int] = set()
        collected: dict[int, list] = {}
        try:
            while True:
                if pos.index >= len(pos.block):
                    if pos.block is root:
                        return
                    pos = self._block_end(pos.block, resume_each)
                    continue
                s = pos.block[pos.index]
                try:
                    pos = self._exec(s, pos, each_state, resume_each, collected)
                except NodeFailure as exc:
                    pos = self._handle(s, pos.block, exc)
                    self._abandon_collects(pos.block, collected, each_state, resume_each)
        finally:
            # Drop private references on every exit, including control errors and
            # cancellation. Published lists and ordinary scope values stay intact.
            self._abandon_collects(None, collected, each_state, resume_each)

    def _abandon_collects(self, block, collected, each_state, resume_each) -> None:
        """Release builders whose owned bodies a failure has exited, including nested ones."""
        active = set()
        while block is not None and id(block) in self.parent:
            parent, _, container = self.parent[id(block)]
            if isinstance(container, Namespace):
                owner = self._owner(container, parent)
                if owner is not None and isinstance(owner[0], Collect):
                    active.add(id(owner[0]))
            block = parent
        for key in tuple(collected):
            if key not in active:
                del collected[key]
                each_state.pop(key, None)
                resume_each.discard(key)

    def _block_end(self, block: list[Stmt], resume_each: set[int]) -> _Pos:
        pblock, i, container = self.parent[id(block)]
        if isinstance(container, Namespace):
            owner = self._owner(container, pblock)
            if owner is not None:
                stmt, oi = owner
                if isinstance(stmt, (Each, Collect)):
                    resume_each.add(id(stmt))
                    return _Pos(pblock, oi)
                labels = stmt.labels
                k = labels.index(container.label)
                if k + 1 < len(labels):
                    _, nxt = self._namespace(pblock, labels[k + 1], False)
                    return _Pos(nxt.body, 0)
                return _Pos(pblock, oi + 1)
        return _Pos(pblock, i + 1)

    def _handle(self, s: Stmt, block: list[Stmt], exc: NodeFailure) -> _Pos:
        """Find the innermost `@try` around the failing statement's block."""
        b = block
        while id(b) in self.parent:
            pblock, i, container = self.parent[id(b)]
            if isinstance(container, Def):
                break
            if isinstance(container, Try) and b is container.body:
                if container.error_name:
                    self.scope.set(
                        container.error_name,
                        {
                            "kind": type(exc.error).__name__,
                            "node": exc.node,
                            "message": str(exc.error),
                        },
                    )
                return _Pos(container.handler, 0)
            b = pblock
        raise exc

    def _exec(self, s: Stmt, pos: _Pos, each_state, resume_each, collected) -> _Pos:
        nxt = _Pos(pos.block, pos.index + 1)
        match s:
            case Namespace() | Def() | TypeHints():
                return nxt
            case Dataflow():
                return _Pos(s.body, 0)
            case Try():
                return _Pos(s.body, 0)
            case Assign():
                self.scope.set(s.target, self._value(s.value))
                return nxt
            case Call():
                self._call(s)
                return nxt
            case Branch():
                cond = self._value(s.cond)
                if not isinstance(cond, bool):
                    raise KirRuntimeError(
                        f"branch condition is {type(cond).__name__}, not bool", s.line
                    )
                return self._enter(pos.block, s.true_label if cond else s.false_label, False)
            case Switch():
                v = self._value(s.value)
                for case, label in s.cases:
                    if case == v:
                        return self._enter(pos.block, label, False)
                if s.default is None:
                    raise KirRuntimeError(f"switch: no case matches {v!r}", s.line)
                return self._enter(pos.block, s.default, False)
            case Jump():
                return self._enter(pos.block, s.label, True)
            case Parallel():
                return self._enter(pos.block, s.labels[0], False)
            case Each() | Collect():
                if id(s) in resume_each:
                    resume_each.discard(id(s))
                    items, k = each_state[id(s)]
                    if isinstance(s, Collect):
                        # Normal completion only: retain the yielded reference in
                        # a private builder, with no host hook or deep copy.
                        collected[id(s)].append(self._value(s.value))
                    k += 1
                else:
                    if isinstance(s, Collect):
                        value = self._value(s.items)
                        try:
                            items = list(value)
                        except KirRuntimeError:
                            raise
                        except Exception as exc:
                            raise NodeFailure(
                                "kir.collect_items", exc, s.line, origin=s.origin
                            ) from exc
                        k = 0
                        collected[id(s)] = []
                    else:
                        items, k = list(self._value(s.items)), 0
                each_state[id(s)] = (items, k)
                if k >= len(items):
                    if isinstance(s, Collect):
                        self.scope.set(s.target, collected.pop(id(s)))
                        each_state.pop(id(s))
                    return nxt
                if s.item is not None:
                    self.scope.set(s.item, items[k])
                if s.index is not None:
                    self.scope.set(s.index, k)
                return self._enter(pos.block, s.label, False)
        raise KirRuntimeError(f"cannot run {type(s).__name__}", s.line)

    def _enter(self, block: list[Stmt], label: str, search_up: bool) -> _Pos:
        _, ns = self._namespace(block, label, search_up)
        return _Pos(ns.body, 0)

    def _value(self, e: Expr) -> Any:
        if isinstance(e, Literal):
            return _fresh(e.value)
        if e.id not in self.scope.values:
            raise KirRuntimeError(f"{e.id!r} is not defined")
        return self.scope.values[e.id]

    # ------------------------------------------------------------ calls
    def _call(self, s: Call) -> None:
        self.steps += 1
        if self.step_budget is not None and self.steps > self.step_budget:
            raise KirRuntimeError(f"more than {self.step_budget} node calls", s.line)
        r = self.env.resolve(s.name)
        if not isinstance(r, Resolved):
            raise KirRuntimeError(f"node {s.name!r} is {r}", s.line)
        sig = r.signature
        event = None
        inputs: dict[str, Any] = {}
        positional = [a for a in s.args if a.key is None]
        for port, a in zip(sig.inputs, positional):
            inputs[port.name] = self._value(a.value)
        for a in s.args:
            if a.key is not None:
                inputs[a.key] = self._value(a.value)
        for port in sig.inputs:
            if port.name not in inputs:
                if port.required:
                    raise KirRuntimeError(f"{s.name}: input {port.name!r} missing", s.line)
                inputs[port.name] = _fresh(port.default)
        if r.definition is not None:
            # The interpreter's own (sorted, indexed) copy, not the env's original.
            try:
                result = self._call_def(self.defs[s.name], inputs)
            except NodeFailure as exc:
                if exc.origin is not None and s.origin is not None:
                    ancestry = (*s.origin.calls, s.origin, *exc.origin.calls)
                    exc.origin = replace(
                        exc.origin,
                        calls=tuple(replace(site, calls=()) for site in ancestry),
                    )
                raise
        else:
            fn = self.nodes.get(s.name) or self.env.impl(s.name)
            if fn is None:
                raise KirRuntimeError(f"no implementation for node {s.name!r}", s.line)

            preparation_error = None
            if is_standard_emit(r.library, sig, fn):
                try:
                    event = Event.capture(inputs["topic"], inputs["payload"])
                except Exception as exc:
                    # The hook must still see invalid emit calls so a recorded
                    # failure consumes its logical invocation during replay.
                    preparation_error = exc

            def run(fn=fn, inputs=inputs):
                if preparation_error is not None:
                    raise preparation_error
                return fn(**inputs)

            try:
                result = self.hook(s.name, inputs, run) if self.hook else run()
                if preparation_error is not None:
                    # A replay cannot turn an invalid payload into a successful
                    # emission merely by skipping the validation thunk.
                    raise preparation_error
            except KirRuntimeError:
                raise
            except Exception as exc:
                raise NodeFailure(s.name, exc, s.line, origin=s.origin) from exc
        self._bind(s, len(sig.outputs), result)
        if event is not None:
            self.events.append(event)
            if self._event_callback is not None:
                try:
                    self._event_callback(event)
                except Exception as exc:
                    # Delivery follows commitment. Never reinterpret a failed
                    # observer as a catchable/retryable source node failure.
                    raise EventDeliveryError(
                        f"committed event delivery failed: {type(exc).__name__}: {exc}", s.line
                    ) from exc

    def _bind(self, s: Call, n_out: int, result: Any) -> None:
        if not s.outs:
            return
        if n_out == 1 or len(s.outs) == 1:
            values = [result]
        else:
            values = list(result)
            if len(values) != len(s.outs):
                raise KirRuntimeError(
                    f"{s.name} returned {len(values)} values for {len(s.outs)} outputs", s.line
                )
        for name, value in zip(s.outs, values):
            if name is not None:
                self.scope.set(name, value)

    def call(self, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run one `@def` as a job: bind ``inputs`` (defaults fill the rest), return its outputs by name."""
        self.events = []
        d = self.defs.get(name)
        if d is None:
            raise KirRuntimeError(f"no @def {name!r}")
        unknown = sorted(set(inputs) - {p.name for p in d.params})
        if unknown:
            raise KirRuntimeError(f"@def {name}: unknown inputs {unknown}")
        self.scope = _Scope()
        bound = dict(inputs)
        for p in d.params:
            if p.name not in bound:
                if p.default is None:
                    raise KirRuntimeError(f"@def {name}: input {p.name!r} missing")
                bound[p.name] = self._value(p.default)
        result = self._call_def(d, bound)
        values = [result] if len(d.outputs) == 1 else list(result)
        return {o.name: v for o, v in zip(d.outputs, values)}

    def _call_def(self, d: Def, inputs: dict[str, Any]) -> Any:
        outer = self.scope
        self.scope = _Scope()
        try:
            for name, value in inputs.items():
                self.scope.set(name, value)
            self._run_block(d.body)
            missing = [o.name for o in d.outputs if o.name not in self.scope.values]
            if missing:
                raise KirRuntimeError(f"@def {d.name}: outputs {missing} not set")
            outs = [self.scope.values[o.name] for o in d.outputs]
        finally:
            self.scope = outer
        return outs[0] if len(outs) == 1 else tuple(outs)


def _fresh(value: Any) -> Any:
    """Literal containers are copied so a node changing one cannot change the program."""
    return copy.deepcopy(value) if isinstance(value, (list, dict, set)) else value


def _bodies(s: Stmt) -> list[list[Stmt]]:
    match s:
        case Namespace() | Dataflow() | Def():
            return [s.body]
        case Try():
            return [s.body, s.handler]
    return []


def _all(stmts: list[Stmt]):
    for s in stmts:
        yield s
        for b in _bodies(s):
            yield from _all(b)


def run(
    program: Program,
    env: NodeEnv,
    nodes: dict[str, Callable] | None = None,
    hook: CallHook | None = None,
    *,
    events: Callable[[Event], None] | None = None,
) -> dict[str, Any]:
    return Interpreter(program, env, nodes, hook, events=events).run()
