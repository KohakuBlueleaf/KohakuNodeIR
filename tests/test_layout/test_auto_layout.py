"""Tests for the auto-layout algorithm."""

from kohakunode.kirgraph.schema import KGEdge, KGNode, KGPort, KirGraph
from kohakunode.layout.auto_layout import auto_layout, estimate_node_size


def _val(nid, pos=None):
    meta = {"pos": pos} if pos else {}
    return KGNode(
        id=nid, type="value", name=nid,
        data_inputs=[], data_outputs=[KGPort(port="value")],
        ctrl_inputs=[], ctrl_outputs=[],
        properties={}, meta=meta,
    )


def _func(nid, n_in=2, n_out=1, ctrl=True, pos=None):
    meta = {"pos": pos} if pos else {}
    return KGNode(
        id=nid, type="add", name=nid,
        data_inputs=[KGPort(port=f"in_{i}") for i in range(n_in)],
        data_outputs=[KGPort(port=f"out_{i}") for i in range(n_out)],
        ctrl_inputs=["in"] if ctrl else [],
        ctrl_outputs=["out"] if ctrl else [],
        properties={}, meta=meta,
    )


def _data(fn, fp, tn, tp):
    return KGEdge(type="data", from_node=fn, from_port=fp, to_node=tn, to_port=tp)


def _ctrl(fn, fp, tn, tp):
    return KGEdge(type="control", from_node=fn, from_port=fp, to_node=tn, to_port=tp)


class TestSizeEstimation:
    def test_value_node(self):
        n = _val("v1")
        w, h = estimate_node_size(n)
        assert w >= 180
        assert h >= 100

    def test_many_ports(self):
        n = _func("f1", n_in=5, n_out=3)
        w, h = estimate_node_size(n)
        assert h > 150  # 5 data rows + header + ctrl rows


class TestAutoLayout:
    def test_preserves_existing_positions(self):
        g = KirGraph(nodes=[
            _val("v1", pos=[100, 200]),
            _val("v2", pos=[300, 400]),
        ], edges=[])
        result = auto_layout(g)
        n1 = next(n for n in result.nodes if n.id == "v1")
        n2 = next(n for n in result.nodes if n.id == "v2")
        assert n1.meta["pos"] == [100, 200]
        assert n2.meta["pos"] == [300, 400]

    def test_assigns_positions_to_unpositioned(self):
        g = KirGraph(nodes=[
            _val("v1"),
            _func("f1"),
        ], edges=[
            _data("v1", "value", "f1", "in_0"),
        ])
        result = auto_layout(g)
        for n in result.nodes:
            pos = n.meta.get("pos")
            assert pos is not None
            assert pos != [0, 0]

    def test_source_before_consumer(self):
        """Source nodes should be placed to the left of consumers."""
        g = KirGraph(nodes=[
            _func("consumer", ctrl=False),
            _func("source", ctrl=False),
        ], edges=[
            _data("source", "out_0", "consumer", "in_0"),
        ])
        result = auto_layout(g)
        src = next(n for n in result.nodes if n.id == "source")
        con = next(n for n in result.nodes if n.id == "consumer")
        assert src.meta["pos"][0] < con.meta["pos"][0]

    def test_no_overlaps(self):
        """Placed nodes should not overlap."""
        g = KirGraph(nodes=[
            _val("v1"), _val("v2"), _val("v3"), _val("v4"),
            _func("f1"), _func("f2"),
        ], edges=[
            _data("v1", "value", "f1", "in_0"),
            _data("v2", "value", "f1", "in_1"),
            _data("v3", "value", "f2", "in_0"),
            _data("v4", "value", "f2", "in_1"),
        ])
        result = auto_layout(g)
        nodes = result.nodes
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                pa, pb = a.meta["pos"], b.meta["pos"]
                sa = a.meta.get("size", [180, 100])
                sb = b.meta.get("size", [180, 100])
                # Check no overlap (with some tolerance)
                x_overlap = pa[0] < pb[0] + sb[0] and pa[0] + sa[0] > pb[0]
                y_overlap = pa[1] < pb[1] + sb[1] and pa[1] + sa[1] > pb[1]
                assert not (x_overlap and y_overlap), f"{a.id} overlaps {b.id}"

    def test_chain_layout(self):
        """A→B→C chain should be laid out left-to-right."""
        g = KirGraph(nodes=[
            _func("c", ctrl=False),
            _func("b", ctrl=False),
            _func("a", ctrl=False),
        ], edges=[
            _data("a", "out_0", "b", "in_0"),
            _data("b", "out_0", "c", "in_0"),
        ])
        result = auto_layout(g)
        a = next(n for n in result.nodes if n.id == "a")
        b = next(n for n in result.nodes if n.id == "b")
        c = next(n for n in result.nodes if n.id == "c")
        assert a.meta["pos"][0] < b.meta["pos"][0] < c.meta["pos"][0]

    def test_mixed_positioned_and_unpositioned(self):
        """Pre-positioned nodes stay, unpositioned ones fill gaps."""
        g = KirGraph(nodes=[
            _val("v1", pos=[100, 100]),
            _func("f1"),  # no position
        ], edges=[
            _data("v1", "value", "f1", "in_0"),
        ])
        result = auto_layout(g)
        v1 = next(n for n in result.nodes if n.id == "v1")
        f1 = next(n for n in result.nodes if n.id == "f1")
        assert v1.meta["pos"] == [100, 100]  # preserved
        assert f1.meta["pos"] != [0, 0]  # assigned
