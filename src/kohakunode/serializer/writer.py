from __future__ import annotations

from typing import Any

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    Expression,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    LabelRef,
    Literal,
    MetaAnnotation,
    ModeDecl,
    Namespace,
    Parallel,
    Parameter,
    Program,
    Statement,
    SubgraphDef,
    Switch,
    Wildcard,
)


class Writer:
    """Walks a KohakuNodeIR AST and emits valid .kir source text.

    Intended for round-tripping (parse -> AST -> serialize -> identical .kir)
    and for compiler output.
    """

    def __init__(self, indent_str: str = "    ") -> None:
        self._indent_str = indent_str

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def write(self, program: Program) -> str:
        """Return the complete .kir source string for *program*."""
        lines: list[str] = []

        if program.mode is not None:
            lines.append(self._write_mode_decl(ModeDecl(mode=program.mode)))
            lines.append("")

        for stmt in program.body:
            lines.extend(self._write_statement(stmt, indent_level=0))

        # Ensure the file ends with a single newline.
        text = "\n".join(lines)
        if text and not text.endswith("\n"):
            text += "\n"
        return text

    # ------------------------------------------------------------------
    # Statement dispatcher
    # ------------------------------------------------------------------

    def _write_statement(self, stmt: Statement, indent_level: int) -> list[str]:
        """Dispatch *stmt* to the appropriate writer; return list of lines."""
        if isinstance(stmt, ModeDecl):
            return [self._write_mode_decl(stmt)]
        if isinstance(stmt, Assignment):
            return self._write_assignment(stmt, indent_level)
        if isinstance(stmt, Branch):
            return self._write_branch(stmt, indent_level)
        if isinstance(stmt, Switch):
            return self._write_switch(stmt, indent_level)
        if isinstance(stmt, Jump):
            return self._write_jump(stmt, indent_level)
        if isinstance(stmt, Parallel):
            return self._write_parallel(stmt, indent_level)
        if isinstance(stmt, FuncCall):
            return self._write_func_call(stmt, indent_level)
        if isinstance(stmt, Namespace):
            return self._write_namespace(stmt, indent_level)
        if isinstance(stmt, SubgraphDef):
            return self._write_subgraph_def(stmt, indent_level)
        if isinstance(stmt, DataflowBlock):
            return self._write_dataflow_block(stmt, indent_level)
        raise TypeError(f"Unknown statement type: {type(stmt)!r}")

    # ------------------------------------------------------------------
    # Statement writers
    # ------------------------------------------------------------------

    def _write_assignment(self, node: Assignment, indent_level: int) -> list[str]:
        """Return metadata lines (if any) followed by ``"    target = value"``."""
        lines: list[str] = []
        prefix = self._indent_str * indent_level
        if node.metadata:
            for meta in node.metadata:
                lines.append(self._write_meta(meta, indent_level))
        value_str = self._write_expression(node.value)
        lines.append(f"{prefix}{node.target} = {value_str}")
        return lines

    def _write_func_call(self, node: FuncCall, indent_level: int) -> list[str]:
        """Return metadata lines followed by ``"    (inputs)func_name(outputs)"``."""
        lines: list[str] = []
        prefix = self._indent_str * indent_level

        lines.extend(self._write_meta_lines(node.metadata, indent_level))

        inputs_str = self._format_input_list(node.inputs)
        outputs_str = self._format_output_list(node.outputs)
        lines.append(f"{prefix}({inputs_str}){node.func_name}({outputs_str})")
        return lines

    def _write_branch(self, node: Branch, indent_level: int) -> list[str]:
        """Return metadata lines followed by ``"    (cond)branch(`true`, `false`)"``."""
        lines: list[str] = []
        prefix = self._indent_str * indent_level

        lines.extend(self._write_meta_lines(node.metadata, indent_level))

        cond_str = self._write_expression(node.condition)
        true_str = f"`{node.true_label}`"
        false_str = f"`{node.false_label}`"
        lines.append(f"{prefix}({cond_str})branch({true_str}, {false_str})")
        return lines

    def _write_switch(self, node: Switch, indent_level: int) -> list[str]:
        """Return metadata lines followed by ``"    (val)switch(0=>`a`, _=>`default`)"``."""
        lines: list[str] = []
        prefix = self._indent_str * indent_level

        lines.extend(self._write_meta_lines(node.metadata, indent_level))

        val_str = self._write_expression(node.value)

        case_parts: list[str] = []
        for expr, label in node.cases:
            key_str = self._write_expression(expr)
            case_parts.append(f"{key_str}=>`{label}`")

        if node.default_label is not None:
            case_parts.append(f"_=>`{node.default_label}`")

        cases_str = ", ".join(case_parts)
        lines.append(f"{prefix}({val_str})switch({cases_str})")
        return lines

    def _write_jump(self, node: Jump, indent_level: int) -> list[str]:
        """Return metadata lines followed by ``"    ()jump(`target`)"``."""
        lines: list[str] = []
        prefix = self._indent_str * indent_level

        lines.extend(self._write_meta_lines(node.metadata, indent_level))

        lines.append(f"{prefix}()jump(`{node.target}`)")
        return lines

    def _write_parallel(self, node: Parallel, indent_level: int) -> list[str]:
        """Return metadata lines followed by ``"    ()parallel(`a`, `b`)"``."""
        lines: list[str] = []
        prefix = self._indent_str * indent_level

        lines.extend(self._write_meta_lines(node.metadata, indent_level))

        labels_str = ", ".join(f"`{lbl}`" for lbl in node.labels)
        lines.append(f"{prefix}()parallel({labels_str})")
        return lines

    def _write_namespace(self, node: Namespace, indent_level: int) -> list[str]:
        """Return label line (``"label:"``), then indented body statements."""
        prefix = self._indent_str * indent_level
        lines: list[str] = [f"{prefix}{node.name}:"]

        for stmt in node.body:
            lines.extend(self._write_statement(stmt, indent_level + 1))

        return lines

    def _write_subgraph_def(self, node: SubgraphDef, indent_level: int) -> list[str]:
        """Return ``"@def name(params)(outputs)"`` line plus indented body."""
        prefix = self._indent_str * indent_level

        params_str = self._format_param_list(node.params)
        outputs_str = ", ".join(node.outputs)

        lines: list[str] = [f"{prefix}@def {node.name}({params_str})({outputs_str})"]

        for stmt in node.body:
            lines.extend(self._write_statement(stmt, indent_level + 1))

        lines.append("")  # blank line after each @def block
        return lines

    def _write_dataflow_block(
        self, node: DataflowBlock, indent_level: int
    ) -> list[str]:
        """Return ``"@dataflow:"`` line plus indented body."""
        prefix = self._indent_str * indent_level
        lines: list[str] = [f"{prefix}@dataflow:"]

        for stmt in node.body:
            lines.extend(self._write_statement(stmt, indent_level + 1))

        return lines

    # ------------------------------------------------------------------
    # Non-statement writers
    # ------------------------------------------------------------------

    def _write_mode_decl(self, node: ModeDecl) -> str:
        """Return ``"@mode dataflow"``."""
        return f"@mode {node.mode}"

    def _write_meta(self, meta: MetaAnnotation, indent_level: int) -> str:
        """Return a single ``"    @meta key=value ..."`` line."""
        prefix = self._indent_str * indent_level
        pairs = " ".join(
            f"{k}={self._write_meta_value(v)}" for k, v in meta.data.items()
        )
        return f"{prefix}@meta {pairs}"

    def _write_expression(self, expr: Expression) -> str:
        """Serialize any expression node to its .kir text form."""
        if isinstance(expr, Literal):
            return self._write_literal(expr)
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, LabelRef):
            return f"`{expr.name}`"
        if isinstance(expr, KeywordArg):
            return f"{expr.name}={self._write_expression(expr.value)}"
        raise TypeError(f"Unknown expression type: {type(expr)!r}")

    def _write_literal(self, lit: Literal) -> str:
        """Return a Python-style literal string for *lit*."""
        value = lit.value
        kind = lit.literal_type

        if kind == "none" or value is None:
            return "None"
        if kind == "bool" or isinstance(value, bool):
            return "True" if value else "False"
        if kind == "int":
            return str(int(value))
        if kind == "float":
            # Preserve a decimal point so the output is unambiguously a float.
            text = repr(float(value))
            return text
        if kind == "str":
            # Use double-quote style.
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if kind == "list":
            items = ", ".join(self._write_expression(item) for item in value)
            return f"[{items}]"
        if kind == "dict":
            pairs = ", ".join(
                f"{self._write_expression(k)}: {self._write_expression(v)}"
                for k, v in value.items()
            )
            return "{" + pairs + "}"

        # Fallback: use repr for anything unrecognised.
        return repr(value)

    def _write_meta_value(self, value: Any) -> str:
        """Serialize a metadata value, handling tuples like ``pos=(100, 200)``."""
        if isinstance(value, tuple):
            inner = ", ".join(self._write_meta_value(item) for item in value)
            return f"({inner})"
        if isinstance(value, bool):
            return "True" if value else "False"
        if value is None:
            return "None"
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(value, list):
            inner = ", ".join(self._write_meta_value(item) for item in value)
            return f"[{inner}]"
        if isinstance(value, dict):
            pairs = ", ".join(
                f"{self._write_meta_value(k)}: {self._write_meta_value(v)}"
                for k, v in value.items()
            )
            return "{" + pairs + "}"
        # int / float / anything else
        return repr(value)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_meta_lines(
        self, metadata: list[MetaAnnotation] | None, indent_level: int
    ) -> list[str]:
        """Return one ``@meta`` line per annotation, or empty list if none."""
        if not metadata:
            return []
        return [self._write_meta(m, indent_level) for m in metadata]

    def _format_input_list(self, inputs: list[Expression]) -> str:
        """Serialize a list of input expressions as a comma-separated string."""
        return ", ".join(self._write_expression(expr) for expr in inputs)

    def _format_output_list(self, outputs: list[str | Wildcard]) -> str:
        """Serialize a list of output names/wildcards as a comma-separated string."""
        parts: list[str] = []
        for item in outputs:
            if isinstance(item, Wildcard):
                parts.append("_")
            else:
                parts.append(str(item))
        return ", ".join(parts)

    def _format_param_list(self, params: list[Parameter]) -> str:
        """Serialize @def parameter list as a comma-separated string."""
        parts: list[str] = []
        for param in params:
            if param.default is not None:
                parts.append(f"{param.name}={self._write_expression(param.default)}")
            else:
                parts.append(param.name)
        return ", ".join(parts)
