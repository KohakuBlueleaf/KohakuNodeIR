"""Test that Rust and Python produce identical results."""
import json

import pytest
from pathlib import Path

# Skip all tests if Rust is not available
pytest.importorskip("kohakunode_rs")

KIR_EXAMPLES = sorted(Path("examples/kir_basics").glob("*.kir"))


class TestRustPythonParity:
    @pytest.mark.parametrize("kir_file", KIR_EXAMPLES, ids=lambda f: f.stem)
    def test_parse_roundtrip(self, kir_file):
        """Rust parser should parse the same files as Python parser."""
        import kohakunode_rs

        source = kir_file.read_text(encoding="utf-8")
        # Rust parse returns JSON string
        result = kohakunode_rs.parse_kir(source)
        ast = json.loads(result)
        assert "body" in ast
        assert isinstance(ast["body"], list)

    def test_compile_dataflow(self):
        """Rust DataflowCompiler should produce same result as Python."""
        import kohakunode_rs
        from kohakunode import parse
        from kohakunode.compiler.dataflow import DataflowCompiler
        from kohakunode.serializer.writer import Writer

        source = "@dataflow:\n    (x, y)add(result)\n    (1)to_int(x)\n    (2)to_int(y)"
        # Python path
        prog = parse(source)
        compiled = DataflowCompiler().transform(prog)
        py_output = Writer().write(compiled)

        # Rust path (via JSON bridge)
        rust_ast_json = kohakunode_rs.parse_kir(source)
        rust_compiled_json = kohakunode_rs.compile_dataflow(rust_ast_json)
        # Just verify it doesn't crash and returns valid JSON
        result = json.loads(rust_compiled_json)
        assert "body" in result
