"""``kir-lsp``: a basic language server for KIR over stdio (needs ``kohakunode[lsp]``).

initializationOptions: ``sigPath`` (signature directories) and ``core``
("rust" or "python"; default "rust" when ``kohakunode._rs`` is built).
"""

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from kohakunode.lsp.analysis import (
    Analysis,
    analyze,
    completions,
    default_core,
    definition,
    format_text,
    hover,
)

SEVERITY = {"error": types.DiagnosticSeverity.Error, "warning": types.DiagnosticSeverity.Warning}
KINDS = {
    "node": types.CompletionItemKind.Function,
    "def": types.CompletionItemKind.Module,
    "builtin": types.CompletionItemKind.Keyword,
    "label": types.CompletionItemKind.Reference,
    "directive": types.CompletionItemKind.Keyword,
}

server = LanguageServer("kir-lsp", "0.2.0")
state: dict = {"sig_path": [], "core": default_core(), "analyses": {}}


def refresh(uri: str) -> Analysis:
    doc = server.workspace.get_text_document(uri)
    a = analyze(doc.source, doc.path, state["sig_path"], state["core"])
    state["analyses"][uri] = a
    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=uri,
            diagnostics=[
                types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=p.line, character=p.start),
                        end=types.Position(line=p.line, character=p.end),
                    ),
                    severity=SEVERITY[p.severity],
                    code=p.code,
                    source="kir",
                    message=p.message,
                )
                for p in a.problems
            ],
        )
    )
    return a


@server.feature(types.INITIALIZE)
def on_initialize(params: types.InitializeParams) -> None:
    options = params.initialization_options or {}
    state["sig_path"] = list(options.get("sigPath", []))
    state["core"] = options.get("core") or default_core()


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(params: types.DidOpenTextDocumentParams) -> None:
    refresh(params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(params: types.DidChangeTextDocumentParams) -> None:
    refresh(params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: types.DidSaveTextDocumentParams) -> None:
    refresh(params.text_document.uri)


def _analysis(uri: str) -> Analysis:
    return state["analyses"].get(uri) or refresh(uri)


@server.feature(types.TEXT_DOCUMENT_HOVER)
def on_hover(params: types.HoverParams) -> types.Hover | None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    text = hover(_analysis(doc.uri), doc.source, params.position.line, params.position.character)
    if text is None:
        return None
    return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=text))


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION, types.CompletionOptions(trigger_characters=["@", "`", ")"])
)
def on_completion(params: types.CompletionParams) -> types.CompletionList:
    doc = server.workspace.get_text_document(params.text_document.uri)
    items = completions(
        state["analyses"].get(doc.uri), doc.source, params.position.line, params.position.character
    )
    return types.CompletionList(
        is_incomplete=False,
        items=[types.CompletionItem(label=label, kind=KINDS[kind]) for label, kind in items],
    )


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def on_definition(params: types.DefinitionParams) -> types.Location | None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    line = definition(
        _analysis(doc.uri), doc.source, params.position.line, params.position.character
    )
    if line is None:
        return None
    pos = types.Position(line=line, character=0)
    return types.Location(uri=doc.uri, range=types.Range(start=pos, end=pos))


@server.feature(types.TEXT_DOCUMENT_FORMATTING)
def on_format(params: types.DocumentFormattingParams) -> list[types.TextEdit] | None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    new = format_text(doc.source, state["core"])
    if new is None or new == doc.source:
        return None
    end = types.Position(line=len(doc.lines), character=0)
    return [
        types.TextEdit(
            range=types.Range(start=types.Position(line=0, character=0), end=end), new_text=new
        )
    ]


def main() -> None:
    server.start_io()


if __name__ == "__main__":
    main()
