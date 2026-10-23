"""KIR (Kohaku Node IR) v2 reference implementation."""

from kohakunode.check import Diagnostic, check
from kohakunode.compiler import Compiled, compile_file, compile_program, compile_source
from kohakunode.errors import (
    EventDeliveryError,
    KirCheckError,
    KirError,
    KirRuntimeError,
    KirSignatureError,
    KirSyntaxError,
    NodeFailure,
)
from kohakunode.events import Event
from kohakunode.lower import full_hash, lower, semantic_hash
from kohakunode.modules import KirModuleError, Linked, link_program
from kohakunode.records import (
    RecordValue,
    construct,
    decode_portable,
    decode_record,
    encode_portable,
    encode_record,
    project,
    replace_field,
)
from kohakunode.run import Interpreter, run
from kohakunode.sig import STD, Library, NodeLibrary, Port, Signature, build_env
from kohakunode.sig.records import RecordField, RecordSchema
from kohakunode.syntax import parse, parse_file, write

__all__ = [
    "STD",
    "Compiled",
    "Diagnostic",
    "Event",
    "EventDeliveryError",
    "Interpreter",
    "KirCheckError",
    "KirError",
    "KirModuleError",
    "KirRuntimeError",
    "KirSignatureError",
    "KirSyntaxError",
    "Library",
    "Linked",
    "NodeFailure",
    "NodeLibrary",
    "Port",
    "RecordField",
    "RecordSchema",
    "RecordValue",
    "Signature",
    "build_env",
    "check",
    "compile_file",
    "compile_program",
    "compile_source",
    "construct",
    "decode_portable",
    "decode_record",
    "encode_portable",
    "encode_record",
    "full_hash",
    "link_program",
    "lower",
    "parse",
    "parse_file",
    "project",
    "replace_field",
    "run",
    "semantic_hash",
    "write",
]
