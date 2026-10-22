"""Node signatures and libraries."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from kohakunode.records import RecordOperation
from kohakunode.sig.records import (
    RecordField,
    RecordSchema,
    generated_names,
    qualify_schema,
    thaw_default,
    validate_record_cycles,
)
from kohakunode.syntax.ast import ANY, TypeExpr

REQUIRED = object()  # default of an input that must be given


@dataclass(frozen=True)
class Port:
    name: str
    type: TypeExpr = ANY
    default: Any = REQUIRED

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


@dataclass(frozen=True)
class Signature:
    name: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    mutates: tuple[str, ...] = ()
    ordered: bool = False
    doc: str = ""

    def input(self, name: str) -> Port | None:
        return next((p for p in self.inputs if p.name == name), None)


@dataclass
class Library:
    """Named signatures, plus implementations when the library was built in Python."""

    name: str
    signatures: dict[str, Signature] = field(default_factory=dict)
    impls: dict[str, Callable] = field(default_factory=dict)
    records: dict[str, RecordSchema] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Constructor-supplied schemas follow the same validation and derivation
        # path as add_record; existing positional arguments remain unchanged.
        records = dict(self.records)
        self.records = {}
        for name, schema in records.items():
            if name != schema.name:
                raise ValueError(f"record key {name!r} differs from schema name {schema.name!r}")
            self.add_record(schema)

    def __contains__(self, node: str) -> bool:
        return node in self.signatures

    def add_signature(self, sig: Signature, impl: Callable | None = None) -> None:
        if sig.name in self.signatures or sig.name in self.records:
            raise ValueError(f"library {self.name!r} already has a node or record {sig.name!r}")
        self.signatures[sig.name] = qualify_record_signature(sig, self.records)
        if impl is not None:
            self.impls[sig.name] = impl

    def add_record(
        self, schema: RecordSchema | str, fields: Sequence[RecordField] | None = None
    ) -> RecordSchema:
        """Register an immutable schema and derive ordinary make/get/with nodes.

        Defaults belong to RecordField(has_default=True, default=...), never
        to the signature REQUIRED sentinel used by legacy host nodes.
        """
        if isinstance(schema, str):
            if fields is None:
                raise ValueError("record fields are required (use an empty sequence for no fields)")
            schema = RecordSchema(schema, tuple(fields))
        elif fields is not None or not isinstance(schema, RecordSchema):
            raise ValueError("add_record expects a RecordSchema or a name and fields")
        schema = qualify_schema(schema, self.name)
        names = generated_names(schema)
        if (
            schema.name in self.records
            or schema.name in self.signatures
            or schema.name in self.impls
        ):
            raise ValueError(f"library {self.name!r} already has a node or record {schema.name!r}")
        collision = next(
            (name for name in names if name in self.signatures or name in self.impls), None
        )
        if collision is not None:
            raise ValueError(f"record {schema.name!r} generated node collision: {collision!r}")
        validate_record_cycles(self.records | {schema.name: schema})
        signatures = record_signatures(schema)
        operations = [RecordOperation(schema, "make")]
        operations.extend(
            RecordOperation(schema, kind, field.name)
            for field in schema.fields
            for kind in ("get", "with")
        )
        # Validation and operation construction finish before mutating the library.
        self.records[schema.name] = schema
        self.signatures.update(
            (name, qualify_record_signature(sig, self.records))
            for name, sig in self.signatures.items()
        )
        for signature, operation in zip(signatures, operations):
            self.signatures[signature.name] = signature
            self.impls[signature.name] = operation
        return schema


def qualify_record_signature(sig: Signature, records: dict[str, RecordSchema]) -> Signature:
    """Qualify known local records without changing unrelated host nominal types."""
    if not records:
        return sig

    def qualify(type_: TypeExpr) -> TypeExpr:
        name = type_.name
        if type_.kind == "name" and name in records:
            name = records[name].schema_id
        return TypeExpr(type_.kind, name, tuple(qualify(arg) for arg in type_.args))

    return replace(
        sig,
        inputs=tuple(replace(port, type=qualify(port.type)) for port in sig.inputs),
        outputs=tuple(replace(port, type=qualify(port.type)) for port in sig.outputs),
    )


def record_signatures(schema: RecordSchema) -> tuple[Signature, ...]:
    """The deterministic visible signatures derived from a registered schema."""
    nominal = TypeExpr("name", schema.schema_id)
    result = [
        Signature(
            f"{schema.name}.make",
            tuple(
                Port(
                    field.name,
                    field.type,
                    thaw_default(field.default) if field.has_default else REQUIRED,
                )
                for field in schema.fields
            ),
            (Port("record", nominal),),
        )
    ]
    for member in schema.fields:
        result.append(
            Signature(
                f"{schema.name}.get.{member.name}",
                (Port("record", nominal),),
                (Port("value", member.type),),
            )
        )
        result.append(
            Signature(
                f"{schema.name}.with.{member.name}",
                (Port("record", nominal), Port("value", member.type)),
                (Port("record", nominal),),
            )
        )
    return tuple(result)
