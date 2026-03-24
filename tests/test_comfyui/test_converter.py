"""Tests for the ComfyUI workflow -> KirGraph converter."""

from __future__ import annotations

from kohakunode.kirgraph.schema import KirGraph
from kohakunode_utils.comfyui import comfyui_to_kirgraph
from kohakunode_utils.comfyui_to_kir import comfyui_to_kir


# ---------------------------------------------------------------------------
# Test workflows (inline dicts)
# ---------------------------------------------------------------------------

WORKFLOW_MINIMAL = {
    "version": 1,
    "nodes": [
        {
            "id": 1,
            "type": "LoadImage",
            "pos": [100, 200],
            "size": [200, 100],
            "inputs": [],
            "outputs": [
                {"name": "IMAGE", "type": "IMAGE", "links": [1]},
            ],
            "widgets_values": ["photo.png"],
            "properties": {},
            "order": 0,
            "mode": 0,
            "flags": {},
        },
        {
            "id": 2,
            "type": "SaveImage",
            "pos": [400, 200],
            "size": [300, 300],
            "inputs": [
                {"name": "images", "type": "IMAGE", "link": 1},
            ],
            "outputs": [],
            "widgets_values": ["ComfyUI"],
            "properties": {},
            "order": 1,
            "mode": 0,
            "flags": {},
        },
    ],
    "links": [[1, 1, 0, 2, 0, "IMAGE"]],
    "groups": [],
    "state": {},
    "extra": {},
}

WORKFLOW_KSAMPLER = {
    "version": 1,
    "nodes": [
        {
            "id": 1,
            "type": "CheckpointLoaderSimple",
            "pos": [100, 100],
            "size": [300, 100],
            "inputs": [],
            "outputs": [
                {"name": "MODEL", "type": "MODEL", "links": [1]},
                {"name": "CLIP", "type": "CLIP", "links": [2, 4]},
                {"name": "VAE", "type": "VAE", "links": [5]},
            ],
            "widgets_values": ["v1-5-pruned-emaonly.ckpt"],
            "properties": {"Node name for S&R": "CheckpointLoaderSimple"},
            "order": 0,
            "mode": 0,
            "flags": {},
        },
        {
            "id": 2,
            "type": "CLIPTextEncode",
            "pos": [450, 50],
            "size": [300, 100],
            "inputs": [{"name": "clip", "type": "CLIP", "link": 2}],
            "outputs": [
                {"name": "CONDITIONING", "type": "CONDITIONING", "links": [3]},
            ],
            "widgets_values": ["a beautiful landscape, mountains, sunset"],
            "properties": {"Node name for S&R": "CLIPTextEncode"},
            "order": 1,
            "mode": 0,
            "flags": {},
        },
        {
            "id": 3,
            "type": "CLIPTextEncode",
            "pos": [450, 200],
            "size": [300, 100],
            "inputs": [{"name": "clip", "type": "CLIP", "link": 4}],
            "outputs": [
                {"name": "CONDITIONING", "type": "CONDITIONING", "links": [6]},
            ],
            "widgets_values": ["blurry, low quality"],
            "properties": {"Node name for S&R": "CLIPTextEncode"},
            "order": 2,
            "mode": 0,
            "flags": {},
        },
        {
            "id": 4,
            "type": "KSampler",
            "pos": [800, 100],
            "size": [300, 200],
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 1},
                {"name": "positive", "type": "CONDITIONING", "link": 3},
                {"name": "negative", "type": "CONDITIONING", "link": 6},
                {"name": "latent_image", "type": "LATENT", "link": 8},
            ],
            "outputs": [
                {"name": "LATENT", "type": "LATENT", "links": [7]},
            ],
            "widgets_values": [42, "fixed", 20, 7.5, "euler", "normal", 1.0],
            "properties": {"Node name for S&R": "KSampler"},
            "order": 4,
            "mode": 0,
            "flags": {},
        },
        {
            "id": 5,
            "type": "EmptyLatentImage",
            "pos": [450, 350],
            "size": [300, 100],
            "inputs": [],
            "outputs": [
                {"name": "LATENT", "type": "LATENT", "links": [8]},
            ],
            "widgets_values": [512, 512, 1],
            "properties": {"Node name for S&R": "EmptyLatentImage"},
            "order": 3,
            "mode": 0,
            "flags": {},
        },
        {
            "id": 6,
            "type": "VAEDecode",
            "pos": [1150, 100],
            "size": [200, 100],
            "inputs": [
                {"name": "samples", "type": "LATENT", "link": 7},
                {"name": "vae", "type": "VAE", "link": 5},
            ],
            "outputs": [
                {"name": "IMAGE", "type": "IMAGE", "links": [9]},
            ],
            "widgets_values": [],
            "properties": {"Node name for S&R": "VAEDecode"},
            "order": 5,
            "mode": 0,
            "flags": {},
        },
        {
            "id": 7,
            "type": "SaveImage",
            "pos": [1400, 100],
            "size": [300, 300],
            "inputs": [
                {"name": "images", "type": "IMAGE", "link": 9},
            ],
            "outputs": [],
            "widgets_values": ["ComfyUI"],
            "properties": {"Node name for S&R": "SaveImage"},
            "order": 6,
            "mode": 0,
            "flags": {},
        },
    ],
    "links": [
        [1, 1, 0, 4, 0, "MODEL"],
        [2, 1, 1, 2, 0, "CLIP"],
        [3, 2, 0, 4, 1, "CONDITIONING"],
        [4, 1, 1, 3, 0, "CLIP"],
        [5, 1, 2, 6, 1, "VAE"],
        [6, 3, 0, 4, 2, "CONDITIONING"],
        [7, 4, 0, 6, 0, "LATENT"],
        [8, 5, 0, 4, 3, "LATENT"],
        [9, 6, 0, 7, 0, "IMAGE"],
    ],
    "groups": [],
    "state": {"lastNodeId": 7, "lastLinkId": 9},
    "extra": {},
}

WORKFLOW_WIDGETS = {
    "version": 1,
    "nodes": [
        {
            "id": 10,
            "type": "EmptyLatentImage",
            "pos": [100, 100],
            "size": [300, 100],
            "inputs": [],
            "outputs": [
                {"name": "LATENT", "type": "LATENT", "links": []},
            ],
            "widgets_values": [512, 768, 4],
            "properties": {},
            "order": 0,
            "mode": 0,
            "flags": {},
        },
    ],
    "links": [],
    "groups": [],
    "state": {},
    "extra": {},
}

# Object-format links workflow
WORKFLOW_OBJECT_LINKS = {
    "version": 1,
    "nodes": [
        {
            "id": 1,
            "type": "NodeA",
            "pos": [0, 0],
            "size": [100, 50],
            "inputs": [],
            "outputs": [{"name": "OUT", "type": "DATA", "links": [1]}],
            "widgets_values": [],
            "properties": {},
        },
        {
            "id": 2,
            "type": "NodeB",
            "pos": [200, 0],
            "size": [100, 50],
            "inputs": [{"name": "IN", "type": "DATA", "link": 1}],
            "outputs": [],
            "widgets_values": [],
            "properties": {},
        },
    ],
    "links": [
        {
            "id": 1,
            "origin_id": 1,
            "origin_slot": 0,
            "target_id": 2,
            "target_slot": 0,
            "type": "DATA",
        },
    ],
    "groups": [],
    "state": {},
    "extra": {},
}

# Workflow with missing optional fields (robustness test)
WORKFLOW_SPARSE = {
    "nodes": [
        {
            "id": 1,
            "type": "SimpleNode",
        },
    ],
    "links": [],
}


# ---------------------------------------------------------------------------
# Tests: basic conversion
# ---------------------------------------------------------------------------


class TestMinimalWorkflow:
    def test_node_count(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        assert len(graph.nodes) == 2

    def test_edge_count(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        assert len(graph.edges) == 1

    def test_node_ids(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        ids = {n.id for n in graph.nodes}
        assert ids == {"comfy_1", "comfy_2"}

    def test_node_types(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        types = {n.id: n.type for n in graph.nodes}
        assert types["comfy_1"] == "loadimage"
        assert types["comfy_2"] == "saveimage"

    def test_node_names_preserve_original(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        names = {n.id: n.name for n in graph.nodes}
        assert names["comfy_1"] == "LoadImage"
        assert names["comfy_2"] == "SaveImage"

    def test_positions(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        node1 = next(n for n in graph.nodes if n.id == "comfy_1")
        assert node1.meta["pos"] == [100, 200]

    def test_edge_data_type(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        assert all(e.type == "data" for e in graph.edges)

    def test_no_control_ports(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        for n in graph.nodes:
            assert n.ctrl_inputs == []
            assert n.ctrl_outputs == []

    def test_edge_connectivity(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        e = graph.edges[0]
        assert e.from_node == "comfy_1"
        assert e.from_port == "image"
        assert e.to_node == "comfy_2"
        assert e.to_port == "images"


class TestKSamplerWorkflow:
    def test_node_count(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        assert len(graph.nodes) == 7

    def test_edge_count(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        assert len(graph.edges) == 9

    def test_all_edges_are_data(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        for e in graph.edges:
            assert e.type == "data"

    def test_no_control_edges(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        assert not any(e.type == "control" for e in graph.edges)

    def test_ksampler_inputs(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        ks = next(n for n in graph.nodes if n.id == "comfy_4")
        input_ports = [p.port for p in ks.data_inputs]
        assert input_ports == ["model", "positive", "negative", "latent_image"]

    def test_checkpoint_outputs(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        ckpt = next(n for n in graph.nodes if n.id == "comfy_1")
        output_ports = [p.port for p in ckpt.data_outputs]
        assert output_ports == ["model", "clip", "vae"]

    def test_ksampler_widget_values(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        ks = next(n for n in graph.nodes if n.id == "comfy_4")
        assert ks.properties["widgets"] == [
            42,
            "fixed",
            20,
            7.5,
            "euler",
            "normal",
            1.0,
        ]

    def test_compile_to_kir(self):
        """Converting to L2 KIR should not raise errors."""
        kir_text = comfyui_to_kir(WORKFLOW_KSAMPLER)
        assert isinstance(kir_text, str)
        assert len(kir_text) > 0
        # Should contain function calls for the node types
        assert "checkpointloadersimple" in kir_text
        assert "ksampler" in kir_text


class TestWidgetDefaults:
    def test_widget_values_stored(self):
        graph = comfyui_to_kirgraph(WORKFLOW_WIDGETS)
        node = graph.nodes[0]
        assert node.properties["widgets"] == [512, 768, 4]

    def test_no_edges(self):
        graph = comfyui_to_kirgraph(WORKFLOW_WIDGETS)
        assert len(graph.edges) == 0

    def test_compile_to_kir(self):
        kir_text = comfyui_to_kir(WORKFLOW_WIDGETS)
        assert isinstance(kir_text, str)
        assert "emptylatentimage" in kir_text


class TestObjectFormatLinks:
    def test_edge_count(self):
        graph = comfyui_to_kirgraph(WORKFLOW_OBJECT_LINKS)
        assert len(graph.edges) == 1

    def test_edge_connectivity(self):
        graph = comfyui_to_kirgraph(WORKFLOW_OBJECT_LINKS)
        e = graph.edges[0]
        assert e.from_node == "comfy_1"
        assert e.from_port == "out"
        assert e.to_node == "comfy_2"
        assert e.to_port == "in"


class TestSparseWorkflow:
    """Test that workflows with missing optional fields are handled."""

    def test_handles_missing_fields(self):
        graph = comfyui_to_kirgraph(WORKFLOW_SPARSE)
        assert len(graph.nodes) == 1
        node = graph.nodes[0]
        assert node.id == "comfy_1"
        assert node.type == "simplenode"
        assert node.data_inputs == []
        assert node.data_outputs == []
        assert node.ctrl_inputs == []
        assert node.ctrl_outputs == []

    def test_default_position(self):
        graph = comfyui_to_kirgraph(WORKFLOW_SPARSE)
        node = graph.nodes[0]
        assert node.meta["pos"] == [0, 0]

    def test_compile_to_kir(self):
        kir_text = comfyui_to_kir(WORKFLOW_SPARSE)
        assert isinstance(kir_text, str)


class TestKirGraphSerialization:
    """Test that the produced KirGraph can be serialized to/from JSON."""

    def test_json_roundtrip(self):
        graph = comfyui_to_kirgraph(WORKFLOW_KSAMPLER)
        json_str = graph.to_json()
        graph2 = KirGraph.from_json(json_str)
        assert len(graph2.nodes) == len(graph.nodes)
        assert len(graph2.edges) == len(graph.edges)

    def test_to_dict(self):
        graph = comfyui_to_kirgraph(WORKFLOW_MINIMAL)
        d = graph.to_dict()
        assert d["version"] == "0.1.0"
        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1


class TestFullPipeline:
    """End-to-end: ComfyUI workflow -> KirGraph -> L2 KIR text."""

    def test_ksampler_pipeline(self):
        kir = comfyui_to_kir(WORKFLOW_KSAMPLER)
        assert isinstance(kir, str)
        # All 7 nodes should appear as function calls in a @dataflow: block
        assert "@dataflow:" in kir

    def test_minimal_pipeline(self):
        kir = comfyui_to_kir(WORKFLOW_MINIMAL)
        assert isinstance(kir, str)
        assert "@dataflow:" in kir

    def test_object_links_pipeline(self):
        kir = comfyui_to_kir(WORKFLOW_OBJECT_LINKS)
        assert isinstance(kir, str)
