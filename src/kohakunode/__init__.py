"""KIR (Kohaku Node IR) v2 reference implementation."""

from kohakunode.check import Diagnostic, check
from kohakunode.compiler import Compiled, compile_file, compile_program, compile_source
from kohakunode.errors import (
    KirCheckError,
    KirError,
    KirRuntimeError,
    KirSignatureError,
    KirSyntaxError,
    NodeFailure,
)
from kohakunode.lower import full_hash, lower, semantic_hash
from kohakunode.modules import KirModuleError, Linked, link_program
from kohakunode.run import Interpreter, run
from kohakunode.sig import STD, Library, NodeLibrary, Port, Signature, build_env
from kohakunode.syntax import parse, parse_file, write

__all__ = [
    "STD",
    "Compiled",
    "Diagnostic",
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
    "Signature",
    "build_env",
    "check",
    "compile_file",
    "compile_program",
    "compile_source",
    "full_hash",
    "link_program",
    "lower",
    "parse",
    "parse_file",
    "run",
    "semantic_hash",
    "write",
]
