"""Signature files (``<library>.kirsig.json``) and `@use` resolution."""

import json
import os
from collections.abc import Iterable
from pathlib import Path

from kohakunode.errors import KirSignatureError
from kohakunode.sig.model import REQUIRED, Library, Port, Signature
from kohakunode.sig.types import parse_type, type_text
from kohakunode.syntax.ast import ANY

SUFFIX = ".kirsig.json"
FORMAT = 1


def library_to_json(lib: Library) -> dict:
    nodes = []
    for sig in lib.signatures.values():
        entry = {
            "name": sig.name,
            "inputs": [_port_json(p, with_default=True) for p in sig.inputs],
            "outputs": [_port_json(p, with_default=False) for p in sig.outputs],
        }
        if sig.mutates or sig.ordered:
            entry["flags"] = {"mutates": list(sig.mutates), "ordered": sig.ordered}
        if sig.doc:
            entry["doc"] = sig.doc
        nodes.append(entry)
    return {"kirsig": FORMAT, "library": lib.name, "nodes": nodes}


def _port_json(p: Port, with_default: bool) -> dict:
    out = {"name": p.name}
    if p.type != ANY:
        out["type"] = type_text(p.type)
    if with_default and not p.required:
        try:
            json.dumps(p.default)
        except TypeError as exc:
            raise KirSignatureError(f"default of {p.name!r} is not JSON: {exc}") from None
        out["default"] = p.default
    return out


def library_from_json(data: dict) -> Library:
    if data.get("kirsig") != FORMAT:
        raise KirSignatureError(f"unsupported signature format {data.get('kirsig')!r}")
    lib = Library(data["library"])
    for entry in data["nodes"]:
        flags = entry.get("flags", {})
        lib.add_signature(
            Signature(
                entry["name"],
                tuple(_port_from(p, True) for p in entry.get("inputs", [])),
                tuple(_port_from(p, False) for p in entry.get("outputs", [])),
                tuple(flags.get("mutates", ())),
                bool(flags.get("ordered", False)),
                entry.get("doc", ""),
            )
        )
    return lib


def _port_from(p: dict, with_default: bool) -> Port:
    t = parse_type(p["type"]) if "type" in p else ANY
    default = p["default"] if with_default and "default" in p else REQUIRED
    return Port(p["name"], t, default)


def save_library(lib: Library, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(library_to_json(lib), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_library(path: str | Path) -> Library:
    try:
        return library_from_json(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError) as exc:
        raise KirSignatureError(f"cannot load signature file {path}: {exc}") from None


def sig_path(extra: Iterable[str | Path] = ()) -> list[Path]:
    """The signature search path: ``extra`` first, then ``KIR_SIG_PATH``."""
    dirs = [Path(p) for p in extra]
    env = os.environ.get("KIR_SIG_PATH", "")
    dirs += [Path(p) for p in env.split(os.pathsep) if p]
    return dirs


def resolve_library(name: str, base_dir: Path | None, search: list[Path]) -> Path:
    """Find the signature file for a `@use` string (signatures.md, "Resolution")."""
    if name.endswith(SUFFIX):
        p = Path(name)
        if not p.is_absolute() and base_dir is not None:
            p = base_dir / p
        if p.is_file():
            return p
        raise KirSignatureError(f"signature file {name!r} not found")
    for d in search:
        p = d / f"{name}{SUFFIX}"
        if p.is_file():
            return p
    raise KirSignatureError(
        f"library {name!r} not found on the signature path {[str(d) for d in search]}"
    )
