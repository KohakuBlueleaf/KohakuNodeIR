"""Tests for layout scoring and optimization."""

from kohakunode.kirgraph.schema import KGEdge, KGNode, KGPort, KirGraph
from kohakunode.layout.auto_layout import auto_layout
from kohakunode.layout.optimizer import optimize_layout
from kohakunode.layout.score import score_layout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(nid, pos, data_in=0, data_out=1, ctrl_in=False, ctrl_out=False):
    """Create a node at an explicit pixel position."""
    return KGNode(
        id=nid,
        type="func",
        name=nid,
        data_inputs=[KGPort(port=f"in_{i}") for i in range(data_in)],
        data_outputs=[KGPort(port=f"out_{i}") for i in range(data_out)],
        ctrl_inputs=["in"] if ctrl_in else [],
        ctrl_outputs=["out"] if ctrl_out else [],
        properties={},
        meta={"pos": list(pos), "size": [180, 100]},
    )


def _data(fn, fp, tn, tp):
    return KGEdge(type="data", from_node=fn, from_port=fp, to_node=tn, to_port=tp)


def _ctrl(fn, fp, tn, tp):
    return KGEdge(
        type="control", from_node=fn, from_port=fp, to_node=tn, to_port=tp
    )


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


class TestPerfectChain:
    """A -> B -> C data chain, columns 0->1->2, same row => score 0."""

    def test_score_zero(self):
        # Three nodes on the same row, each 1 column apart
        # Using distinct x values that sort to col 0, 1, 2 and same y
        g = KirGraph(
            nodes=[
                _node("A", pos=[100, 100]),
                _node("B", pos=[340, 100]),
                _node("C", pos=[580, 100]),
            ],
            edges=[
                _data("A", "out_0", "B", "in_0"),
                _data("B", "out_0", "C", "in_0"),
            ],
        )
        result = score_layout(g)
        assert result.total == 0.0
        assert result.max_edge_cost == 0.0
        assert result.avg_edge_cost == 0.0


class TestBadLayout:
    """Same chain but reversed columns => high score."""

    def test_reversed_columns_high_cost(self):
        # C is at col 0, B at col 1, A at col 2 — data flows backwards
        g = KirGraph(
            nodes=[
                _node("A", pos=[580, 100]),
                _node("B", pos=[340, 100]),
                _node("C", pos=[100, 100]),
            ],
            edges=[
                _data("A", "out_0", "B", "in_0"),
                _data("B", "out_0", "C", "in_0"),
            ],
        )
        result = score_layout(g)
        # Both edges flow backward (col_diff < 0): cost = |col_diff|*3 + |row_diff|
        # A(col=2) -> B(col=1): col_diff=-1, backward => 1*3+0 = 3
        # B(col=1) -> C(col=0): col_diff=-1, backward => 1*3+0 = 3
        assert result.total == 6.0
        assert result.max_edge_cost == 3.0


class TestCtrlVertical:
    """A -> B -> C control chain, same column, rows 0->1->2 => score 0."""

    def test_score_zero(self):
        g = KirGraph(
            nodes=[
                _node("A", pos=[100, 100], ctrl_in=False, ctrl_out=True),
                _node("B", pos=[100, 240], ctrl_in=True, ctrl_out=True),
                _node("C", pos=[100, 380], ctrl_in=True, ctrl_out=False),
            ],
            edges=[
                _ctrl("A", "out", "B", "in"),
                _ctrl("B", "out", "C", "in"),
            ],
        )
        result = score_layout(g)
        assert result.total == 0.0
        assert result.max_edge_cost == 0.0


class TestMixedLayout:
    """Realistic graph — verify optimize_layout improves the score."""

    def test_optimizer_improves(self):
        # Build a graph with intentionally sub-optimal positions
        g = KirGraph(
            nodes=[
                _node("src", pos=[500, 500]),  # should be leftmost
                _node("mid", pos=[100, 100]),  # should be middle
                _node("dst", pos=[300, 300]),  # should be rightmost
            ],
            edges=[
                _data("src", "out_0", "mid", "in_0"),
                _data("mid", "out_0", "dst", "in_0"),
            ],
        )
        before = score_layout(g)
        assert before.total > 0

        optimized = optimize_layout(g)
        after = score_layout(optimized)
        assert after.total <= before.total


class TestOptimizerConverges:
    """Verify optimizer terminates and doesn't worsen the score."""

    def test_does_not_worsen(self):
        # Simple data pipeline — auto_layout first, then optimize
        nodes = [
            KGNode(
                id=f"n{i}",
                type="func",
                name=f"n{i}",
                data_inputs=[KGPort(port="in_0")] if i > 0 else [],
                data_outputs=[KGPort(port="out_0")] if i < 4 else [],
                ctrl_inputs=[],
                ctrl_outputs=[],
                properties={},
                meta={},
            )
            for i in range(5)
        ]
        edges = [
            _data(f"n{i}", "out_0", f"n{i+1}", "in_0") for i in range(4)
        ]
        g = KirGraph(nodes=nodes, edges=edges)

        laid_out = auto_layout(g)
        before = score_layout(laid_out)

        optimized = optimize_layout(g)
        after = score_layout(optimized)

        # Optimizer must not make things worse
        assert after.total <= before.total

    def test_already_optimal(self):
        """If the layout is already perfect the optimizer must not break it."""
        g = KirGraph(
            nodes=[
                _node("A", pos=[100, 100]),
                _node("B", pos=[340, 100]),
            ],
            edges=[
                _data("A", "out_0", "B", "in_0"),
            ],
        )
        optimized = optimize_layout(g)
        result = score_layout(optimized)
        assert result.total == 0.0


class TestEdgeBreakdown:
    """Verify per-edge breakdown is populated."""

    def test_edge_count_matches(self):
        g = KirGraph(
            nodes=[
                _node("A", pos=[100, 100]),
                _node("B", pos=[340, 200]),
            ],
            edges=[
                _data("A", "out_0", "B", "in_0"),
            ],
        )
        result = score_layout(g)
        assert len(result.edge_scores) == 1
        es = result.edge_scores[0]
        assert es.col_diff == 1
        assert es.row_diff == 1
        # Data edge: col_diff=1 (ideal), row_diff=1 => cost = 0 + 1*2 = 2
        assert es.cost == 2.0
