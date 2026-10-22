"""Signature files (``<library>.kirsig.json``) and `@use` resolution."""

import json
import os
from collections.abc import Iterable
from pathlib import Path

from kohakunode.errors import KirSignatureError
from kohakunode.sig.model import REQUIRED, Library, Port, Signature, record_signatures
from kohakunode.sig.records import RecordField, RecordSchema, portable_default_equal, thaw_default
from kohakunode.sig.types import parse_type, type_text
from kohakunode.syntax.ast import ANY

SUFFIX = ".kirsig.json"
FORMAT = 1
RECORD_FORMAT = 2


def library_to_json(lib: Library) -> dict:
    generated = {}
    for schema in lib.records.values():
        for signature in record_signatures(schema):
            if not _same_generated_signature(lib.signatures.get(signature.name), signature):
                raise KirSignatureError(f"generated record node {signature.name!r} was modified")
            generated[signature.name] = signature
    nodes = []
    for sig in lib.signatures.values():
        if sig.name in generated:
            continue
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
    result = {
        "kirsig": RECORD_FORMAT if lib.records else FORMAT,
        "library": lib.name,
        "nodes": nodes,
    }
    if lib.records:
        result["records"] = [
            {
                "name": schema.name,
                "fields": [
                    {
                        "name": field.name,
                        "type": type_text(field.type),
                        **({"default": thaw_default(field.default)} if field.has_default else {}),
                    }
                    for field in schema.fields
                ],
            }
            for schema in lib.records.values()
        ]
    return result


def _same_default(actual, expected) -> bool:
    if expected is REQUIRED:
        return actual is REQUIRED
    return portable_default_equal(actual, expected)


def _same_generated_signature(actual: Signature | None, expected: Signature) -> bool:
    if type(actual) is not Signature:
        return False
    if (actual.name, actual.mutates, actual.ordered, actual.doc) != (
        expected.name,
        expected.mutates,
        expected.ordered,
        expected.doc,
    ):
        return False
    for actual_ports, expected_ports in (
        (actual.inputs, expected.inputs),
        (actual.outputs, expected.outputs),
    ):
        if len(actual_ports) != len(expected_ports):
            return False
        if any(
            a.name != b.name or a.type != b.type or not _same_default(a.default, b.default)
            for a, b in zip(actual_ports, expected_ports)
        ):
            return False
    return True


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
    if type(data.get("kirsig")) is not int or data["kirsig"] not in (FORMAT, RECORD_FORMAT):
        raise KirSignatureError(f"unsupported signature format {data.get('kirsig')!r}")
    if data["kirsig"] == FORMAT and data.get("records"):
        raise KirSignatureError("record schemas require signature format 2")
    lib = Library(data["library"])
    for entry in data["nodes"]:
        flags = entry.get("flags", {})
        signature = Signature(
            entry["name"],
            tuple(_port_from(p, True) for p in entry.get("inputs", [])),
            tuple(_port_from(p, False) for p in entry.get("outputs", [])),
            tuple(flags.get("mutates", ())),
            bool(flags.get("ordered", False)),
            entry.get("doc", ""),
        )
        try:
            lib.add_signature(signature)
        except ValueError as exc:
            raise KirSignatureError(str(exc)) from None
    if data["kirsig"] == RECORD_FORMAT:
        try:
            for record in data.get("records", []):
                schema = RecordSchema(
                    record["name"],
                    tuple(
                        RecordField(
                            field["name"],
                            _record_field_type(field),
                            "default" in field,
                            field.get("default"),
                        )
                        for field in record["fields"]
                    ),
                )
                lib.add_record(schema)
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            raise KirSignatureError(f"invalid record schema: {exc}") from None
    return lib


def _record_field_type(field: dict):
    text = field.get("type")
    if type(text) is not str:
        raise ValueError("record field type must be an explicit string (use '_' for any)")
    return parse_type(text)


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
