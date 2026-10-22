"""Deterministic source-module linking before checking and lowering.

Source imports never execute a module. Resolvers return text; the linker keeps
implementation bodies visible and isolates each module's definition namespace.
"""

import copy
import hashlib
import json
import math
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from kohakunode.errors import KirSignatureError, KirSyntaxError
from kohakunode.lower import semantic_hash
from kohakunode.origins import stamp_origins
from kohakunode.sig.env import NodeEnv, Resolved, build_env
from kohakunode.sig.files import library_to_json
from kohakunode.sig.model import Library
from kohakunode.sig.std import STD
from kohakunode.syntax.ast import (
    Assign,
    Call,
    Def,
    Namespace,
    Program,
    Try,
    TypeExpr,
    TypeHints,
    Use,
    labels_entered,
    reads,
    walk,
    writes,
)
from kohakunode.syntax.parser import parse

# Builtin value types are shared; undeclared nominal names belong to their module.
BUILTIN_TYPES = frozenset(
    {
        "bool",
        "int",
        "float",
        "str",
        "None",
        "list",
        "dict",
        "tuple",
        "set",
        "bytes",
        "object",
        "complex",
    }
)
PREFIX = "_kir_"


class KirModuleError(KirSignatureError):
    """An import, export, or module namespace cannot be linked."""


@dataclass
class Linked:
    program: Program
    libraries: list[Library]
    dependencies: dict = field(default_factory=dict)


@dataclass
class _Module:
    name: str
    program: Program
    env: NodeEnv
    imports: dict[str, str]
    definitions: dict[str, Def]
    chain: tuple[str, ...]


def _prefix(module: str) -> str:
    return PREFIX + hashlib.sha256(module.encode("utf-8")).hexdigest()[:16] + "__"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _contract_value(value, active: set[int]) -> None:
    """JSON object keys must not silently stringify into another default's identity."""
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("default floats must be finite")
        return
    if type(value) not in (dict, list):
        raise ValueError(f"default {type(value).__name__!r} is not portable JSON data")
    if isinstance(value, (dict, list)):
        if id(value) in active:
            raise ValueError("cyclic default")
        active.add(id(value))
        try:
            if isinstance(value, dict):
                if any(type(key) is not str for key in value):
                    raise ValueError("default object keys must be strings")
                values = value.values()
            else:
                values = value
            for item in values:
                _contract_value(item, active)
        finally:
            active.remove(id(value))


def contract_hash(lib: Library) -> str:
    """Hash the portable signature contract, excluding documentation and implementation."""
    try:
        for signature in lib.signatures.values():
            for port in signature.inputs:
                if not port.required:
                    _contract_value(port.default, set())
    except ValueError as exc:
        raise KirModuleError(
            f"library {lib.name!r} has a nonportable signature default: {exc}"
        ) from None
    contract = library_to_json(lib)
    for node in contract["nodes"]:
        node.pop("doc", None)
    contract["nodes"].sort(key=lambda n: n["name"])
    try:
        encoded = _canonical(contract)
    except (TypeError, ValueError) as exc:
        raise KirModuleError(
            f"library {lib.name!r} has a nonportable signature default: {exc}"
        ) from None
    return hashlib.sha256(encoded).hexdigest()


def _module_id(request: str, importer: str) -> str:
    """Normalize a portable resource path without consulting the host filesystem."""
    if not request or "\\" in request or ":" in request or request.startswith("/"):
        raise KirModuleError(f"invalid module resource {request!r}: use a relative POSIX path")
    name = posixpath.normpath(posixpath.join(posixpath.dirname(importer), request))
    if name in (".", "..") or name.startswith("../"):
        raise KirModuleError(f"module resource {request!r} escapes the package root")
    return name


def _type_names(t: TypeExpr | None) -> set[str]:
    if t is None:
        return set()
    names = {t.name} if t.name else set()
    for arg in t.args:
        names.update(_type_names(arg))
    return names


def _public_types(module: _Module) -> set[str]:
    names: set[str] = set()
    for name in module.program.exports:
        definition = module.definitions[name]
        for port in (*definition.params, *definition.outputs):
            names.update(_type_names(port.type))
    return names


class _Linker:
    def __init__(self, libraries, base_dir, sig_path, modules, source_name):
        self.libraries = list(libraries or [])
        self.base = Path(base_dir) if base_dir is not None else None
        self.sig_path = sig_path
        self.sources = modules
        self.root = source_name
        self.loaded: dict[str, _Module] = {}
        self.active: list[str] = []
        self.active_files: list[Path] = []
        self.uses: list[Use] = []
        self.hosts: dict[str, Library] = {}

    def read(self, name: str) -> str:
        if self.sources is not None:
            if name not in self.sources:
                raise KirModuleError(f"module {name!r} is missing from the module map")
            return self.sources[name]
        if self.base is None:
            raise KirModuleError(f"module {name!r} needs a module map or a base directory")
        root = self.base.resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise KirModuleError(f"module {name!r} resolves outside the package root")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise KirModuleError(f"cannot read module {name!r}: {exc}") from None

    def visit(self, name: str, program: Program | None = None) -> None:
        if name in self.active:
            raise KirModuleError("import cycle: " + " -> ".join([*self.active, name]))
        if name in self.loaded:
            return
        physical = None
        if self.sources is None and self.base is not None and name != "<text>":
            physical = (self.base / name).resolve()
            if physical in self.active_files:
                raise KirModuleError("import cycle: " + " -> ".join([*self.active, name]))
            self.active_files.append(physical)
        self.active.append(name)
        try:
            if program is None:
                program = parse(self.read(name))
            program = stamp_origins(program, name)
            if name != self.root:
                if program.mode is not None or any(
                    not isinstance(s, (Def, TypeHints)) for s in program.body
                ):
                    raise KirModuleError("imported modules contain declarations only")
            definitions: dict[str, Def] = {}
            for stmt in walk(program.body):
                names = reads(stmt) + writes(stmt) + labels_entered(stmt)
                match stmt:
                    case Def():
                        names += [
                            stmt.name,
                            *(p.name for p in stmt.params),
                            *(p.name for p in stmt.outputs),
                        ]
                    case Namespace():
                        names.append(stmt.label)
                    case TypeHints():
                        names += [entry.name for entry in stmt.entries]
                    case Call():
                        names.append(stmt.name)
                    case Try() if stmt.error_name is not None:
                        names.append(stmt.error_name)
                if any(n.startswith(PREFIX) for n in names):
                    raise KirModuleError(f"authored names cannot use reserved prefix {PREFIX!r}")
                if not isinstance(stmt, Def):
                    continue
                if stmt.name.startswith(PREFIX) or stmt.name in definitions:
                    raise KirModuleError(f"duplicate or reserved definition {stmt.name!r}")
                definitions[stmt.name] = stmt
            exports: set[str] = set()
            top = {s.name for s in program.body if isinstance(s, Def)}
            for export in program.exports:
                if export in exports:
                    raise KirModuleError(f"duplicate export {export!r}")
                if export not in top:
                    raise KirModuleError(f"export {export!r} is not a top-level definition")
                exports.add(export)
            env = build_env(program, self.libraries, self.base_for(name), self.sig_path)
            aliases = {u.alias for u in program.uses if u.alias is not None}
            if any(alias.startswith(PREFIX) for alias in aliases):
                raise KirModuleError(f"signature aliases cannot use reserved prefix {PREFIX!r}")
            imports: dict[str, str] = {}
            for imp in program.imports:
                if imp.alias.startswith(PREFIX):
                    raise KirModuleError(f"import aliases cannot use reserved prefix {PREFIX!r}")
                if imp.alias in imports or imp.alias in aliases or imp.alias in definitions:
                    raise KirModuleError(f"ambiguous import alias {imp.alias!r}")
                target = _module_id(imp.module, name)
                imports[imp.alias] = target
                self.visit(target)
            self.loaded[name] = _Module(
                name, program, env, imports, definitions, tuple(self.active)
            )
        except (KirSignatureError, KirSyntaxError) as exc:
            if isinstance(exc, KirModuleError) and str(exc).startswith("import chain "):
                raise
            raise KirModuleError(f"import chain {' -> '.join(self.active)}: {exc}") from None
        finally:
            self.active.pop()
            if physical is not None:
                self.active_files.pop()

    def base_for(self, name: str) -> Path | None:
        return self.base / str(PurePosixPath(name).parent) if self.base is not None else None

    def definition_name(self, module: _Module, name: str) -> str:
        return name if module.name == self.root else _prefix(module.name) + name

    def host_aliases(self, module: _Module) -> dict[int, str]:
        aliases: dict[int, str] = {}
        libraries = list(module.env.libraries)
        if module.name != self.root and not any(lib is STD for lib, _ in libraries):
            libraries.append((STD, None))
        for i, (lib, original_alias) in enumerate(libraries):
            if lib.name in self.hosts:
                if contract_hash(self.hosts[lib.name]) != contract_hash(lib):
                    raise KirModuleError(
                        f"incompatible signature libraries share name {lib.name!r}"
                    )
            else:
                self.hosts[lib.name] = lib
            alias = _prefix(module.name) + f"lib{i}"
            aliases[id(lib)] = alias
            if module.name != self.root:
                self.uses.append(Use(lib.name, alias))
            elif original_alias is None and not any(
                u.library == lib.name for u in self.uses[: len(module.program.uses)]
            ):
                self.uses.append(Use(lib.name))
        return aliases

    def type_name(self, module: _Module, name: str) -> str:
        if name.startswith(PREFIX):
            raise KirModuleError(f"authored types cannot use reserved prefix {PREFIX!r}")
        head, dot, rest = name.partition(".")
        if dot and head in module.imports:
            target = self.loaded[module.imports[head]]
            if rest not in _public_types(target):
                raise KirModuleError(f"{module.name}: type {name!r} is not public")
            return self.type_name(target, rest)
        if not name or name in BUILTIN_TYPES:
            return name
        # Host nominal types retain their declared contract identity.
        for lib, _ in module.env.libraries:
            for sig in lib.signatures.values():
                for port in (*sig.inputs, *sig.outputs):
                    if name in _type_names(port.type):
                        return name
        return _prefix(module.name) + name

    def rewrite(self, module: _Module) -> list:
        program = copy.deepcopy(module.program)
        aliases = self.host_aliases(module)

        def typ(t: TypeExpr | None) -> TypeExpr | None:
            return (
                None
                if t is None
                else TypeExpr(t.kind, self.type_name(module, t.name), tuple(typ(a) for a in t.args))
            )

        for stmt in walk(program.body):
            match stmt:
                case Def():
                    stmt.name = self.definition_name(module, stmt.name)
                    stmt.params = [replace(p, type=typ(p.type)) for p in stmt.params]
                    stmt.outputs = [replace(p, type=typ(p.type)) for p in stmt.outputs]
                case Assign():
                    stmt.type = typ(stmt.type)
                case TypeHints():
                    stmt.entries = [
                        replace(
                            e,
                            name=(
                                e.name
                                if module.name == self.root
                                else _prefix(module.name) + "hint." + e.name
                            ),
                            inputs=tuple(typ(t) for t in e.inputs),
                            outputs=tuple(typ(t) for t in e.outputs),
                        )
                        for e in stmt.entries
                    ]
                case Call():
                    head, dot, rest = stmt.name.partition(".")
                    if dot and head in module.imports:
                        target = self.loaded[module.imports[head]]
                        if rest not in target.program.exports:
                            raise KirModuleError(
                                f"{module.name}:{stmt.line}: {stmt.name!r} is not exported by {target.name!r}"
                            )
                        stmt.name = self.definition_name(target, rest)
                    elif stmt.name in module.definitions:
                        stmt.name = self.definition_name(module, stmt.name)
                    else:
                        resolved = module.env.resolve(stmt.name)
                        if not isinstance(resolved, Resolved):
                            raise KirModuleError(
                                f"{module.name}:{stmt.line}: node {stmt.name!r} is {resolved}"
                            )
                        if module.name != self.root:
                            if resolved.library is not None:
                                alias = aliases.get(id(resolved.library))
                                if alias is not None:
                                    stmt.name = alias + "." + resolved.signature.name
                            elif stmt.name in module.env.typehints:
                                stmt.name = _prefix(module.name) + "hint." + stmt.name
        return program.body

    def portable_uses(self, module: _Module) -> list[Use]:
        # Signature file locations are resolution inputs, not dependency identities.
        return [
            Use(lib.name, use.alias)
            for use, (lib, _) in zip(module.program.uses, module.env.libraries)
        ]

    def manifest(self) -> dict:
        modules = []
        for name, module in sorted(self.loaded.items()):
            source = copy.deepcopy(module.program)
            source.uses = self.portable_uses(module)
            modules.append(
                {
                    "module": name,
                    "semantic_hash": semantic_hash(source),
                    "imports": dict(sorted(module.imports.items())),
                    "exports": sorted(module.program.exports),
                }
            )
        contracts = [
            {"library": name, "hash": contract_hash(lib)}
            for name, lib in sorted(self.hosts.items())
        ]
        identity = {"version": 1, "modules": modules, "signatures": contracts}
        return {**identity, "hash": hashlib.sha256(_canonical(identity)).hexdigest()}

    def link(self, program: Program) -> Linked:
        self.visit(self.root, program)
        root = self.loaded[self.root]
        self.uses = self.portable_uses(root)
        body = []
        for name in sorted(self.loaded):
            if name != self.root:
                body.extend(self.rewrite(self.loaded[name]))
        body.extend(self.rewrite(root))
        linked = Program(uses=self.uses, body=body, mode=root.program.mode)
        return Linked(linked, list(self.hosts.values()), self.manifest())


def link_program(
    program: Program,
    libraries: list[Library] | None = None,
    base_dir: Path | None = None,
    sig_path: list[Path] | None = None,
    *,
    modules: Mapping[str, str] | None = None,
    source_name: str = "<text>",
) -> Linked:
    """Link imports using an authoritative module map or a local package directory.

    ``source_name`` is a portable package-relative resource ID, not an absolute
    source path. Existing programs without module declarations retain their hashes.
    """
    if source_name != "<text>":
        source_name = _module_id(source_name, "")
    if not program.imports and not program.exports:
        result = stamp_origins(program, source_name)
        return Linked(result, list(libraries or []))
    return _Linker(libraries, base_dir, sig_path, modules, source_name).link(program)
