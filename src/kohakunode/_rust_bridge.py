"""Bridge between Python AST and Rust JSON-based functions.

Handles serialization: Python Program → JSON → Rust → JSON → Python Program.
Each function returns None if Rust is unavailable or fails, so callers can fall back.
"""

import json

from kohakunode._rust import HAS_RUST, kohakunode_rs


def _program_to_json(program) -> str:
    """Serialize a Python Program AST to JSON for Rust consumption."""
    from kohakunode.serializer.json_serializer import program_to_dict

    return json.dumps(program_to_dict(program))


def _json_to_program(json_str: str):
    """Deserialize JSON back to a Python Program AST."""
    from kohakunode.serializer.json_serializer import dict_to_program

    return dict_to_program(json.loads(json_str))


def rust_parse(source: str):
    """Parse KIR source using Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        result_json = kohakunode_rs.parse_kir(source)
        return _json_to_program(result_json)
    except Exception:
        return None


def rust_compile_dataflow(program):
    """Run DataflowCompiler via Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        return _json_to_program(kohakunode_rs.compile_dataflow(_program_to_json(program)))
    except Exception:
        return None


def rust_strip_meta(program):
    """Run StripMetaPass via Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        return _json_to_program(kohakunode_rs.strip_meta(_program_to_json(program)))
    except Exception:
        return None


def rust_optimize(program, passes=None):
    """Run L4 Optimizer via Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        passes_json = json.dumps(passes) if passes else None
        return _json_to_program(kohakunode_rs.optimize(_program_to_json(program), passes_json))
    except Exception:
        return None


def rust_sanitize(program, strip_meta=True, resolve_dataflow=True, type_check=True, remove_dead_code=True):
    """Run configurable Sanitizer via Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        return _json_to_program(
            kohakunode_rs.sanitize(
                _program_to_json(program), strip_meta, resolve_dataflow, type_check, remove_dead_code
            )
        )
    except Exception:
        return None


def rust_eliminate_dead_code(program):
    """Run DeadCodePass via Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        return _json_to_program(kohakunode_rs.eliminate_dead_code(_program_to_json(program)))
    except Exception:
        return None


def rust_type_check(program):
    """Run TypeCheckPass via Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        return _json_to_program(kohakunode_rs.type_check(_program_to_json(program)))
    except Exception:
        return None


def rust_compile_kirgraph(kirgraph_json: str):
    """Compile KirGraph JSON → Program via Rust. Returns Program or None."""
    if not HAS_RUST:
        return None
    try:
        return _json_to_program(kohakunode_rs.compile_kirgraph(kirgraph_json))
    except Exception:
        return None
