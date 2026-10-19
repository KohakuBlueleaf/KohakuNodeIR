"""Request bodies. Responses are the toolchain's dicts as they are."""

from pydantic import BaseModel, Field

from kir_editor.core.toolchain import Scope


class ScopedRequest(BaseModel):
    """Signature files (parsed ``.kirsig.json``) the client holds, and whether ``demo`` is given."""

    signatures: list[dict] = Field(default_factory=list)
    use_demo: bool = True

    def scope(self) -> Scope:
        return Scope(self.signatures, self.use_demo)


class SourceRequest(ScopedRequest):
    text: str


class CompileRequest(SourceRequest):
    """``passes``: optimization passes to run, in order; None runs all, [] none."""

    passes: list[str] | None = None


class GraphRequest(ScopedRequest):
    """A graph document (``.kirgraph``, version 2)."""

    graph: dict
    with_meta: bool = True
