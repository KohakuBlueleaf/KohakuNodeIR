"""IR pass that strips @meta annotations from all statements (L2 → L3)."""

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    FuncCall,
    Jump,
    Namespace,
    Parallel,
    Program,
    Statement,
    SubgraphDef,
    Switch,
    TryExcept,
    TypeHintBlock,
)
from kohakunode.compiler.passes import IRPass


class StripMetaPass(IRPass):
    """Remove @meta annotations from every statement that carries them.

    This converts Level 2 KIR (with metadata for round-tripping) into
    Level 3 KIR (pure execution logic).
    """

    @property
    def name(self) -> str:
        return "strip_meta"

    def transform(self, program: Program) -> Program:
        # Try Rust implementation first
        from kohakunode._rust_bridge import rust_strip_meta

        result = rust_strip_meta(program)
        if result is not None:
            return result

        # Fall back to Python
        new_body = self._strip_body(program.body)
        return Program(body=new_body, mode=program.mode)

    def _strip_body(self, stmts: list[Statement]) -> list[Statement]:
        result: list[Statement] = []
        for stmt in stmts:
            result.append(self._strip_stmt(stmt))
        return result

    def _strip_stmt(self, stmt: Statement) -> Statement:
        # Clear metadata on types that carry it
        match stmt:
            case Assignment():
                return Assignment(
                    target=stmt.target,
                    value=stmt.value,
                    metadata=None,
                    line=stmt.line,
                )
            case FuncCall():
                return FuncCall(
                    inputs=stmt.inputs,
                    func_name=stmt.func_name,
                    outputs=stmt.outputs,
                    metadata=None,
                    line=stmt.line,
                )
            case Branch():
                return Branch(
                    condition=stmt.condition,
                    true_label=stmt.true_label,
                    false_label=stmt.false_label,
                    metadata=None,
                    line=stmt.line,
                )
            case Switch():
                return Switch(
                    value=stmt.value,
                    cases=stmt.cases,
                    default_label=stmt.default_label,
                    metadata=None,
                    line=stmt.line,
                )
            case Jump():
                return Jump(target=stmt.target, metadata=None, line=stmt.line)
            case Parallel():
                return Parallel(labels=stmt.labels, metadata=None, line=stmt.line)
            case Namespace():
                return Namespace(
                    name=stmt.name,
                    body=self._strip_body(stmt.body),
                    line=stmt.line,
                )
            case SubgraphDef():
                return SubgraphDef(
                    name=stmt.name,
                    params=stmt.params,
                    outputs=stmt.outputs,
                    body=self._strip_body(stmt.body),
                    line=stmt.line,
                )
            case TryExcept():
                return TryExcept(
                    try_body=self._strip_body(stmt.try_body),
                    except_body=self._strip_body(stmt.except_body),
                    metadata=None,
                    line=stmt.line,
                )
            case TypeHintBlock():
                # TypeHintBlock is declarative metadata, not executable — pass through.
                return stmt
            case _:
                return stmt
