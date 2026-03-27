"""Configurable L3 Sanitizer that composes compiler passes."""

from dataclasses import dataclass, field

from kohakunode.ast.nodes import Program
from kohakunode.compiler.dataflow import DataflowCompiler
from kohakunode.compiler.dead_code import DeadCodePass
from kohakunode.compiler.passes import IRPass, PassPipeline
from kohakunode.compiler.strip_meta import StripMetaPass
from kohakunode.compiler.type_check import TypeCheckPass


# ---------------------------------------------------------------------------
# SanitizerConfig
# ---------------------------------------------------------------------------


@dataclass
class SanitizerConfig:
    """Feature flags for the :class:`Sanitizer` pass.

    All flags default to ``True`` (all passes enabled).

    Attributes
    ----------
    strip_meta:
        Run :class:`~kohakunode.compiler.strip_meta.StripMetaPass` — remove
        ``@meta`` annotations (L2 → L3 conversion).
    resolve_dataflow:
        Run :class:`~kohakunode.compiler.dataflow.DataflowCompiler` — reorder
        statements by data dependency when ``@mode dataflow`` is set or scoped
        ``@dataflow:`` blocks are present.
    type_check:
        Run :class:`~kohakunode.compiler.type_check.TypeCheckPass` — validate
        variable types against ``@typehint`` declarations.
    remove_dead_code:
        Run :class:`~kohakunode.compiler.dead_code.DeadCodePass` — remove
        assignments whose outputs are never used.
    """

    strip_meta: bool = field(default=True)
    resolve_dataflow: bool = field(default=True)
    type_check: bool = field(default=True)
    remove_dead_code: bool = field(default=True)


# ---------------------------------------------------------------------------
# Sanitizer
# ---------------------------------------------------------------------------


class Sanitizer(IRPass):
    """Configurable L3 sanitizer that composes existing and new passes.

    The passes are applied in the following fixed order (when enabled):

    1. ``strip_meta``       — remove @meta annotations
    2. ``resolve_dataflow`` — topologically sort dataflow statements
    3. ``type_check``       — validate types against @typehint declarations
    4. ``remove_dead_code`` — eliminate unused assignments

    Parameters
    ----------
    config:
        A :class:`SanitizerConfig` instance controlling which passes are
        active.  When ``None`` the default config (all passes enabled) is
        used.
    """

    def __init__(self, config: SanitizerConfig | None = None) -> None:
        self._config = config if config is not None else SanitizerConfig()
        self._pipeline = self._build_pipeline()

    # ------------------------------------------------------------------
    # IRPass interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "sanitizer"

    def transform(self, program: Program) -> Program:
        """Apply all enabled passes in order and return the sanitized program."""
        return self._pipeline.transform(program)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_pipeline(self) -> PassPipeline:
        passes: list[IRPass] = []
        cfg = self._config

        if cfg.strip_meta:
            passes.append(StripMetaPass())

        if cfg.resolve_dataflow:
            passes.append(DataflowCompiler())

        if cfg.type_check:
            passes.append(TypeCheckPass())

        if cfg.remove_dead_code:
            passes.append(DeadCodePass())

        return PassPipeline(passes)
