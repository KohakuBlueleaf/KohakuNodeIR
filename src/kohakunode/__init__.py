"""KohakuNodeIR — public API surface."""

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# AST types
# ---------------------------------------------------------------------------

from kohakunode.ast.nodes import ASTNode
from kohakunode.ast.nodes import Expression
from kohakunode.ast.nodes import Statement
from kohakunode.ast.nodes import Identifier
from kohakunode.ast.nodes import KeywordArg
from kohakunode.ast.nodes import LabelRef
from kohakunode.ast.nodes import Literal
from kohakunode.ast.nodes import MetaAnnotation
from kohakunode.ast.nodes import Parameter
from kohakunode.ast.nodes import Wildcard
from kohakunode.ast.nodes import Assignment
from kohakunode.ast.nodes import Branch
from kohakunode.ast.nodes import DataflowBlock
from kohakunode.ast.nodes import FuncCall
from kohakunode.ast.nodes import Jump
from kohakunode.ast.nodes import ModeDecl
from kohakunode.ast.nodes import Namespace
from kohakunode.ast.nodes import Parallel
from kohakunode.ast.nodes import SubgraphDef
from kohakunode.ast.nodes import Switch
from kohakunode.ast.nodes import Program

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

from kohakunode.parser.parser import parse
from kohakunode.parser.parser import parse_file

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

from kohakunode.engine.context import VariableStore
from kohakunode.engine.executor import Executor
from kohakunode.engine.executor import run
from kohakunode.engine.executor import run_file
from kohakunode.engine.interpreter import Interpreter
from kohakunode.engine.registry import FunctionSpec
from kohakunode.engine.registry import Registry

# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

from kohakunode.analyzer.validator import ValidationResult
from kohakunode.analyzer.validator import validate
from kohakunode.analyzer.validator import validate_or_raise

# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

from kohakunode.compiler.dataflow import DataflowCompiler

# ---------------------------------------------------------------------------
# KirGraph (L1 IR)
# ---------------------------------------------------------------------------

from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.kirgraph.decompiler import KirGraphDecompiler
from kohakunode.kirgraph.schema import KirGraph

# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

from kohakunode.serializer.reader import read
from kohakunode.serializer.reader import read_string
from kohakunode.serializer.writer import Writer

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

from kohakunode.errors import KirError
from kohakunode.errors import KirAnalysisError
from kohakunode.errors import KirCompilationError
from kohakunode.errors import KirRuntimeError
from kohakunode.errors import KirSyntaxError

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # version
    "__version__",
    # AST — base
    "ASTNode",
    "Expression",
    "Statement",
    # AST — expressions
    "Identifier",
    "KeywordArg",
    "LabelRef",
    "Literal",
    # AST — other nodes
    "MetaAnnotation",
    "Parameter",
    "Wildcard",
    # AST — statements
    "Assignment",
    "Branch",
    "DataflowBlock",
    "FuncCall",
    "Jump",
    "ModeDecl",
    "Namespace",
    "Parallel",
    "SubgraphDef",
    "Switch",
    # AST — root
    "Program",
    # Parser
    "parse",
    "parse_file",
    # Engine
    "Executor",
    "FunctionSpec",
    "Interpreter",
    "Registry",
    "VariableStore",
    "run",
    "run_file",
    # Analyzer
    "ValidationResult",
    "validate",
    "validate_or_raise",
    # Compiler
    "DataflowCompiler",
    # KirGraph (L1 IR)
    "KirGraph",
    "KirGraphCompiler",
    "KirGraphDecompiler",
    # Serializer
    "read",
    "read_string",
    "Writer",
    # Errors
    "KirError",
    "KirAnalysisError",
    "KirCompilationError",
    "KirRuntimeError",
    "KirSyntaxError",
]
