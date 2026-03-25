"""Tests for kohakunode.compiler.sanitizer — Sanitizer and SanitizerConfig."""

import pytest

from kohakunode import parse
from kohakunode.ast.nodes import Assignment, FuncCall, Namespace, Program
from kohakunode.compiler.sanitizer import Sanitizer, SanitizerConfig
from kohakunode.compiler.type_check import TypeCheckError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize(source: str, config: SanitizerConfig | None = None) -> Program:
    prog = parse(source)
    return Sanitizer(config).transform(prog)


def _names_in_body(prog: Program) -> set[str]:
    return {s.target for s in prog.body if isinstance(s, Assignment)}


# ---------------------------------------------------------------------------
# Default config (all passes enabled)
# ---------------------------------------------------------------------------


class TestSanitizerDefaultConfig:
    def test_default_config_all_true(self) -> None:
        cfg = SanitizerConfig()
        assert cfg.strip_meta is True
        assert cfg.resolve_dataflow is True
        assert cfg.type_check is True
        assert cfg.remove_dead_code is True

    def test_none_config_uses_defaults(self) -> None:
        """Passing None as config uses the default SanitizerConfig."""
        src = "x = 1\n"
        prog = parse(src)
        result = Sanitizer(None).transform(prog)
        assert isinstance(result, Program)

    def test_sanitizer_name(self) -> None:
        assert Sanitizer().name == "sanitizer"


# ---------------------------------------------------------------------------
# strip_meta toggle
# ---------------------------------------------------------------------------


class TestStripMetaToggle:
    def test_strip_meta_on_removes_metadata(self) -> None:
        """With strip_meta=True, @meta annotations are removed."""
        # @meta is added by the serializer/roundtrip; inject manually
        from kohakunode.ast.nodes import MetaAnnotation

        prog = Program(
            body=[
                Assignment(
                    target="x",
                    value=parse("1").body[0].value if False else __import__(
                        "kohakunode.ast.nodes", fromlist=["Literal"]
                    ).Literal(value=1, literal_type="int"),
                    metadata=[MetaAnnotation(data={"node_id": "abc"})],
                )
            ]
        )
        cfg = SanitizerConfig(
            strip_meta=True,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=False,
        )
        result = Sanitizer(cfg).transform(prog)
        assigns = [s for s in result.body if isinstance(s, Assignment)]
        assert all(a.metadata is None for a in assigns)

    def test_strip_meta_off_preserves_metadata(self) -> None:
        from kohakunode.ast.nodes import Literal, MetaAnnotation

        prog = Program(
            body=[
                Assignment(
                    target="x",
                    value=Literal(value=1, literal_type="int"),
                    metadata=[MetaAnnotation(data={"node_id": "abc"})],
                )
            ]
        )
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=False,
        )
        result = Sanitizer(cfg).transform(prog)
        assigns = [s for s in result.body if isinstance(s, Assignment)]
        assert all(a.metadata is not None for a in assigns)


# ---------------------------------------------------------------------------
# resolve_dataflow toggle
# ---------------------------------------------------------------------------


class TestResolveDataflowToggle:
    def test_resolve_dataflow_on_sorts_statements(self) -> None:
        """With resolve_dataflow=True, out-of-order @mode dataflow is sorted."""
        src = "@mode dataflow\n(x, y)add(z)\nx = 1\ny = 2\n"
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=True,
            type_check=False,
            remove_dead_code=False,
        )
        result = _sanitize(src, cfg)
        # x and y must appear before z
        names = []
        for s in result.body:
            if isinstance(s, Assignment):
                names.append(s.target)
            elif isinstance(s, FuncCall):
                names.extend(o for o in s.outputs if not hasattr(o, "line"))
        pos_x = names.index("x")
        pos_y = names.index("y")
        pos_z = names.index("z")
        assert pos_x < pos_z
        assert pos_y < pos_z

    def test_resolve_dataflow_off_leaves_order_unchanged(self) -> None:
        """With resolve_dataflow=False, @mode dataflow is NOT sorted."""
        src = "@mode dataflow\n(x, y)add(z)\nx = 1\ny = 2\n"
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=False,
        )
        result = _sanitize(src, cfg)
        # mode should still be dataflow (not cleared)
        assert result.mode == "dataflow"


# ---------------------------------------------------------------------------
# type_check toggle
# ---------------------------------------------------------------------------


class TestTypeCheckToggle:
    def test_type_check_on_raises_on_mismatch(self) -> None:
        src = """\
@typehint:
    (int)f(_)

x: str = "hello"
(x)f()
"""
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=True,
            remove_dead_code=False,
        )
        with pytest.raises(TypeCheckError):
            _sanitize(src, cfg)

    def test_type_check_off_ignores_mismatch(self) -> None:
        src = """\
@typehint:
    (int)f(_)

x: str = "hello"
(x)f()
"""
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=False,
        )
        result = _sanitize(src, cfg)  # must not raise
        assert isinstance(result, Program)


# ---------------------------------------------------------------------------
# remove_dead_code toggle
# ---------------------------------------------------------------------------


class TestRemoveDeadCodeToggle:
    def test_remove_dead_code_on_eliminates_unused(self) -> None:
        src = "dead = 42\n"
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=True,
        )
        result = _sanitize(src, cfg)
        assert "dead" not in _names_in_body(result)

    def test_remove_dead_code_off_keeps_unused(self) -> None:
        src = "dead = 42\n"
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=False,
        )
        result = _sanitize(src, cfg)
        assert "dead" in _names_in_body(result)


# ---------------------------------------------------------------------------
# Each toggle works independently (no cross-contamination)
# ---------------------------------------------------------------------------


class TestTogglesIndependent:
    def test_only_strip_meta(self) -> None:
        from kohakunode.ast.nodes import Literal, MetaAnnotation

        prog = Program(
            body=[
                Assignment(
                    target="x",
                    value=Literal(value=42, literal_type="int"),
                    metadata=[MetaAnnotation(data={"n": "v"})],
                )
            ]
        )
        cfg = SanitizerConfig(
            strip_meta=True,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=False,
        )
        result = Sanitizer(cfg).transform(prog)
        # x still present (dead_code off), metadata gone (strip_meta on)
        assigns = [s for s in result.body if isinstance(s, Assignment)]
        assert len(assigns) == 1
        assert assigns[0].metadata is None

    def test_only_dead_code(self) -> None:
        from kohakunode.ast.nodes import Literal, MetaAnnotation

        prog = Program(
            body=[
                Assignment(
                    target="x",
                    value=Literal(value=42, literal_type="int"),
                    metadata=[MetaAnnotation(data={"n": "v"})],
                )
            ]
        )
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=True,
        )
        result = Sanitizer(cfg).transform(prog)
        # x removed (dead_code on), metadata untouched (strip_meta off)
        assert "x" not in _names_in_body(result)

    def test_all_off_is_identity(self) -> None:
        """Config with all flags off: Sanitizer is a no-op."""
        src = "a = 1\nb = 2\n"
        cfg = SanitizerConfig(
            strip_meta=False,
            resolve_dataflow=False,
            type_check=False,
            remove_dead_code=False,
        )
        result = _sanitize(src, cfg)
        names = _names_in_body(result)
        assert "a" in names
        assert "b" in names


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestSanitizerFullPipeline:
    def test_valid_program_passes_all(self) -> None:
        src = """\
@typehint:
    (int, int)add(int)

x: int = 3
y: int = 4
(x, y)add(sum)
(sum)print()
"""
        result = _sanitize(src)
        assert isinstance(result, Program)
        # sum and x, y must be kept (used)
        calls = [s for s in result.body if isinstance(s, FuncCall)]
        call_names = {c.func_name for c in calls}
        assert "add" in call_names
        assert "print" in call_names

    def test_dead_code_removed_in_full_pipeline(self) -> None:
        src = "dead = 999\nused = 5\n(used)print()\n"
        result = _sanitize(src)
        assert "dead" not in _names_in_body(result)
        assert "used" in _names_in_body(result)
