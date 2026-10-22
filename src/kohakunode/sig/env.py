"""Resolve the node names a program calls (signatures.md, "`@use`")."""

import copy
from dataclasses import dataclass, field, replace
from pathlib import Path

from kohakunode.errors import KirSignatureError
from kohakunode.sig.files import load_library, resolve_library, sig_path
from kohakunode.sig.model import Library, Port, Signature
from kohakunode.sig.records import (
    RecordSchema,
    nominal_references,
    record_schema_equal,
    validate_record_cycles,
)
from kohakunode.sig.std import INTERNAL, STD
from kohakunode.syntax.ast import ANY, Assign, Def, Literal, Program, TypeExpr, TypeHints, walk


@dataclass
class Resolved:
    """What a node name refers to: a library signature or a `@def`."""

    signature: Signature
    library: Library | None = None
    definition: Def | None = None


@dataclass
class NodeEnv:
    libraries: list[tuple[Library, str | None]] = field(default_factory=list)
    defs: dict[str, Def] = field(default_factory=dict)
    typehints: dict[str, Signature] = field(default_factory=dict)
    internal: bool = False

    def resolve(self, name: str) -> Resolved | str:
        """A :class:`Resolved`, or an error string ("unknown" / "ambiguous: ...")."""
        if name in self.defs:
            return Resolved(def_signature(self.defs[name]), definition=self.defs[name])
        if name.startswith("kir.") and name in INTERNAL:
            return Resolved(INTERNAL.signatures[name], INTERNAL) if self.internal else "reserved"
        head, _, rest = name.partition(".")
        for lib, alias in self.libraries:
            if alias is not None and alias == head and rest in lib:
                return Resolved(lib.signatures[rest], lib)
        hits = [lib for lib, alias in self.libraries if alias is None and name in lib]
        if len(hits) > 1:
            return "ambiguous: " + ", ".join(lib.name for lib in hits)
        if hits:
            return Resolved(hits[0].signatures[name], hits[0])
        if name in self.typehints:
            return Resolved(self.typehints[name])
        if name in STD:
            return Resolved(STD.signatures[name], STD)
        return "unknown"

    def record_schemas(self) -> dict[str, RecordSchema]:
        """Canonical schemas available to this environment, independent of aliases."""
        records: dict[str, RecordSchema] = {}
        for library, _ in self.libraries:
            for schema in library.records.values():
                previous = records.get(schema.schema_id)
                if previous is not None and not record_schema_equal(previous, schema):
                    raise KirSignatureError(f"conflicting record schema {schema.schema_id!r}")
                records[schema.schema_id] = schema
        return records

    def record_type(self, type_: TypeExpr) -> TypeExpr:
        """Canonicalize known schema names; preserve unrelated nominal host types."""
        name = type_.name
        if type_.kind == "name":
            records = self.record_schemas()
            if name not in records:
                head, dot, rest = name.partition(".")
                hits = {
                    schema.schema_id
                    for library, alias in self.libraries
                    for local, schema in library.records.items()
                    if (alias is None and name == local)
                    or (dot and alias == head and rest == local)
                }
                if len(hits) > 1:
                    raise KirSignatureError(
                        f"ambiguous record type {name!r}: {', '.join(sorted(hits))}"
                    )
                if hits:
                    name = next(iter(hits))
        return TypeExpr(type_.kind, name, tuple(self.record_type(arg) for arg in type_.args))

    def impl(self, name: str):
        r = self.resolve(name)
        if isinstance(r, Resolved) and r.library is not None:
            return r.library.impls.get(r.signature.name)
        return None


def def_signature(d: Def) -> Signature:
    inputs = []
    for p in d.params:
        if p.default is None:
            inputs.append(Port(p.name, p.type or ANY))
        else:
            default = p.default.value if isinstance(p.default, Literal) else None
            inputs.append(Port(p.name, p.type or ANY, default))
    return Signature(d.name, tuple(inputs), tuple(Port(o.name, o.type or ANY) for o in d.outputs))


def build_env(
    program: Program,
    libraries: list[Library] | None = None,
    base_dir: Path | None = None,
    search: list[Path] | None = None,
    internal: bool = False,
    *,
    validate_records: bool = True,
) -> NodeEnv:
    """The node environment of a program.

    ``libraries`` are extra libraries given directly (unaliased); `@use`
    entries are resolved against them first by name, then on the signature
    path.
    """
    given = {lib.name: lib for lib in libraries or []}
    env = NodeEnv(internal=internal)
    used = set()
    for use in program.uses:
        lib = given.get(use.library)
        if lib is None:
            if use.library == STD.name:
                lib = STD
            else:
                lib = load_library(resolve_library(use.library, base_dir, sig_path(search or [])))
        env.libraries.append((lib, use.alias))
        used.add(lib.name)
    for lib in libraries or []:
        if lib.name not in used:
            env.libraries.append((lib, None))
    # Validate the complete loaded schema graph after all libraries are available.
    records = env.record_schemas()
    if validate_records:
        for schema in records.values():
            for field_ in schema.fields:
                for reference in nominal_references(field_.type):
                    if reference not in records:
                        raise KirSignatureError(
                            f"record {schema.schema_id!r} field {field_.name!r} references unknown schema {reference!r}"
                        )
        try:
            validate_record_cycles(records)
        except ValueError as exc:
            raise KirSignatureError(str(exc)) from None
    for s in walk(program.body):
        if isinstance(s, Def):
            env.defs[s.name] = s
        elif isinstance(s, TypeHints):
            for e in s.entries:
                env.typehints[e.name] = Signature(
                    e.name,
                    tuple(Port(f"in{i}", t) for i, t in enumerate(e.inputs)),
                    tuple(Port(f"out{i}", t) for i, t in enumerate(e.outputs)),
                )
    return env


def qualify_record_types(program: Program, env: NodeEnv) -> Program:
    """Copy annotations into canonical schema identity without altering authored text."""
    result = copy.deepcopy(program)

    def typ(type_: TypeExpr | None) -> TypeExpr | None:
        return None if type_ is None else env.record_type(type_)

    for stmt in walk(result.body):
        match stmt:
            case Def():
                stmt.params = [replace(p, type=typ(p.type)) for p in stmt.params]
                stmt.outputs = [replace(p, type=typ(p.type)) for p in stmt.outputs]
            case Assign():
                stmt.type = typ(stmt.type)
            case TypeHints():
                stmt.entries = [
                    replace(
                        e,
                        inputs=tuple(typ(t) for t in e.inputs),
                        outputs=tuple(typ(t) for t in e.outputs),
                    )
                    for e in stmt.entries
                ]
    return result
