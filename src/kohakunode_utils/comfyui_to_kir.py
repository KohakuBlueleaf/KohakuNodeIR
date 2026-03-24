"""Convert ComfyUI workflow JSON directly to L2 KIR text."""

from kohakunode.kirgraph.compiler import KirGraphCompiler
from kohakunode.serializer.writer import Writer
from kohakunode_utils.comfyui import comfyui_to_kirgraph


def comfyui_to_kir(workflow: dict) -> str:
    """Convert a ComfyUI workflow dict to L2 KIR text.

    This is a convenience function that chains:
    1. ComfyUI workflow -> KirGraph (L1)
    2. KirGraph (L1) -> KIR Program AST (L2)
    3. KIR Program AST (L2) -> KIR text

    Args:
        workflow: Parsed ComfyUI workflow JSON dict

    Returns:
        L2 KIR source text string
    """
    graph = comfyui_to_kirgraph(workflow)
    compiler = KirGraphCompiler()
    program = compiler.compile(graph)
    writer = Writer()
    return writer.write(program)
