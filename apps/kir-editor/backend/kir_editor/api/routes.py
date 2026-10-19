"""The editor's HTTP API: one route per toolchain operation."""

from fastapi import APIRouter, Request

from kir_editor.api.schemas import CompileRequest, GraphRequest, SourceRequest
from kir_editor.core.toolchain import Toolchain

router = APIRouter(prefix="/api")


def _tc(request: Request) -> Toolchain:
    return request.app.state.toolchain


@router.post("/graph")
def text_to_graph(body: SourceRequest, request: Request) -> dict:
    """KIR text -> ``{graph, outline, diagnostics}``."""
    return _tc(request).graph(body.text, body.scope())


@router.post("/text")
def graph_to_text(body: GraphRequest, request: Request) -> dict:
    """Graph document -> ``{text, outline, diagnostics}``."""
    return _tc(request).text(body.graph, body.scope(), body.with_meta)


@router.post("/check")
def check(body: SourceRequest, request: Request) -> dict:
    """KIR text -> ``{diagnostics}``."""
    return _tc(request).check(body.text, body.scope())


@router.post("/lower")
def lower(body: CompileRequest, request: Request) -> dict:
    """KIR text -> ``{lowered, semantic_hash, full_hash, diagnostics}`` after the passes."""
    return _tc(request).lower(body.text, body.scope(), body.passes)


@router.post("/run")
def run(body: CompileRequest, request: Request) -> dict:
    """Run on the reference interpreter -> ``{ok, values, stdout, diagnostics}``."""
    return _tc(request).run(body.text, body.scope(), body.passes)


@router.get("/passes")
def passes(request: Request) -> dict:
    """The optimization passes in run order -> ``{passes: [{name, doc}]}``."""
    return {"passes": _tc(request).passes()}


@router.get("/signatures")
def signatures(request: Request) -> dict:
    """Every library the backend knows -> ``{libraries: [kirsig json + source]}``."""
    return {"libraries": _tc(request).catalog()}


@router.get("/health")
def health() -> dict:
    return {"ok": True}
