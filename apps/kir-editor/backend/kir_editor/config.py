"""Backend settings, read from the environment."""

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SIG_DIR = Path(__file__).resolve().parent.parent / "signatures"


@dataclass(frozen=True)
class Settings:
    sig_dirs: list[Path] = field(default_factory=lambda: [DEFAULT_SIG_DIR])
    step_budget: int = 200_000


def load_settings() -> Settings:
    """``KIR_EDITOR_SIG_DIR``: directories of ``.kirsig.json`` files (os.pathsep separated)."""
    raw = os.environ.get("KIR_EDITOR_SIG_DIR", "")
    dirs = [Path(p) for p in raw.split(os.pathsep) if p] or [DEFAULT_SIG_DIR]
    budget = int(os.environ.get("KIR_EDITOR_STEP_BUDGET", "200000"))
    return Settings(sig_dirs=dirs, step_budget=budget)
