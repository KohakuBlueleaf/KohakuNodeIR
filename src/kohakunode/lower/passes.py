"""Optimization passes (passes.md): each rewrites a program into a simpler program.

Every pass takes and returns KIR in the same language, so a program may stop
after any of them and still run on the interpreter. ``lower`` runs them all,
giving the most directly interpretable form: no `@def`, no `each`, every
name versioned, straight runs grouped in `@dataflow:` blocks.
"""

import copy
import hashlib
from collections.abc import Callable

from kohakunode.flow.order import sort_dataflow
from kohakunode.lower.collect import CollectExpander
from kohakunode.lower.each import EachExpander
from kohakunode.lower.inline import Inliner
from kohakunode.lower.versions import version_program
from kohakunode.origins import derive_origin
from kohakunode.sig.env import NodeEnv, Resolved
from kohakunode.syntax.ast import (
    Assign,
    Call,
    Collect,
    Dataflow,
    Program,
    Stmt,
    TypeHints,
    children,
    reads,
    walk,
    writes,
)
from kohakunode.syntax.writer import write

Pass = Callable[[Program, NodeEnv], None]


def order_dataflow(p: Program, env: NodeEnv) -> None:
    """Put every `@dataflow:` block in stable data order; apply `@mode dataflow`."""

    def is_ordered(s: Stmt) -> bool:
        if isinstance(s, Call):
            r = env.resolve(s.name)
            return isinstance(r, Resolved) and r.signature.ordered
        return False

    sort_dataflow(p, is_ordered)
    p.mode = None


def expand_collect(p: Program, env: NodeEnv) -> None:
    """Lower collect to a private fresh-list accumulator, each, and final publication."""
    p.body = CollectExpander(p).block(p.body)


def inline(p: Program, env: NodeEnv) -> None:
    """Replace every `@def` call by a renamed copy of its body; drop the `@def`s."""
    p.body = Inliner(p).block(p.body)


def expand_each(p: Program, env: NodeEnv) -> None:
    """Rewrite every `each` as a loop of `jump`, `branch` and internal nodes."""
    p.body = EachExpander().block(p.body)


def version(p: Program, env: NodeEnv) -> None:
    """Give every write its own version; home versions where several writes reach a read."""
    version_program(p)


def group(p: Program, env: NodeEnv) -> None:
    """Wrap straight runs in `@dataflow:` blocks (typehints first)."""
    hints = [s for s in p.body if isinstance(s, TypeHints)]
    rest = [s for s in p.body if not isinstance(s, TypeHints)]
    p.body = hints + _group(rest)


def strip_meta(p: Program, env: NodeEnv) -> None:
    """Drop `@meta` (editor data); `@hint` and source origins stay."""
    for s in walk(p.body):
        s.meta = {}


# The order matters: inlining needs sorted bodies, versioning needs the flat
# control flow inlining and each expansion produce.
PASSES: dict[str, Pass] = {
    "order_dataflow": order_dataflow,
    "expand_collect": expand_collect,
    "inline": inline,
    "expand_each": expand_each,
    "version": version,
    "group": group,
    "strip_meta": strip_meta,
}


# Passes that must have run earlier in the same list.
REQUIRES = {
    "inline": ["order_dataflow"],
    "version": ["order_dataflow", "inline", "expand_each"],
}


def run_passes(program: Program, env: NodeEnv, names: list[str] | None = None) -> Program:
    """A rewritten copy of a checked program, after the named passes (default: all, in order)."""
    names = list(PASSES) if names is None else list(names)
    for i, name in enumerate(names):
        missing = [r for r in REQUIRES.get(name, []) if r not in names[:i]]
        if name not in PASSES or missing:
            raise ValueError(
                f"pass {name!r} needs {missing} before it" if missing else f"unknown pass {name!r}"
            )
    p = copy.deepcopy(program)
    for name in names:
        if name in ("expand_each", "version") and any(
            isinstance(stmt, Collect) for stmt in walk(p.body)
        ):
            raise ValueError(f"pass {name!r} needs 'expand_collect' while collect remains")
        PASSES[name](p, env)
    return p


def lower(program: Program, env: NodeEnv) -> Program:
    """Every pass: the most directly interpretable form of a checked program."""
    return run_passes(program, env)


def _group_run(run: list[Stmt]) -> Dataflow:
    """Attribute a new wrapper to its first sourced statement; retain all child origins."""
    origin = next((s.origin for s in run if s.origin is not None), None)
    return Dataflow(run, origin=derive_origin(origin, generated="group"))


def _group(stmts: list[Stmt]) -> list[Stmt]:
    """Wrap straight runs of assignments and calls in `@dataflow:` blocks.

    A run is split before a statement that writes a name an earlier statement
    of the run reads (a home version read at a loop's top and written back at
    its end). No block then reads a name a later statement of it writes, so
    ordering a block by data gives back its text order: the result means the
    same whether or not anyone sorts it again.
    """
    flat: list[Stmt] = []
    for s in stmts:
        if isinstance(s, Dataflow):
            flat.extend(s.body)
        else:
            flat.append(s)
    out: list[Stmt] = []
    run: list[Stmt] = []
    read: set[str] = set()
    for s in flat:
        if isinstance(s, (Assign, Call)):
            if read & set(writes(s)):
                out.append(_group_run(run))
                run, read = [], set()
            run.append(s)
            read |= set(reads(s))
            continue
        if run:
            out.append(_group_run(run))
            run, read = [], set()
        for body in children(s):
            body[:] = _group(body)
        out.append(s)
    if run:
        out.append(_group_run(run))
    return out


def semantic_hash(p: Program) -> str:
    """SHA-256 of the canonical text without `@meta` or `@hint`."""
    q = copy.deepcopy(p)
    for s in walk(q.body):
        s.hint = {}
        s.meta = {}
    return hashlib.sha256(write(q).encode("utf-8")).hexdigest()


def full_hash(p: Program) -> str:
    """SHA-256 of the canonical text without `@meta` (hints included)."""
    q = copy.deepcopy(p)
    for s in walk(q.body):
        s.meta = {}
    return hashlib.sha256(write(q).encode("utf-8")).hexdigest()
