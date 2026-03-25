"""Rust backend detection. If kohakunode_rs is available, HAS_RUST=True."""
try:
    import kohakunode_rs

    HAS_RUST = True
except ImportError:
    kohakunode_rs = None
    HAS_RUST = False
