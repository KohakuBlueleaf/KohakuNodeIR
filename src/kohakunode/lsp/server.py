"""``kir-lsp``: a basic language server for KIR over stdio (needs ``kohakunode[lsp]``).

initializationOptions: ``sigPath`` (signature directories) and ``core``
("rust" or "python"; default "rust" when ``kohakunode._rs`` is built).
"""

from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from kohakunode.lsp.analysis import (
    Analysis,
    analyze,
    completions,
    default_core,
    definition_location,
    format_text,
    hover,
    signature_help,
    word_at,
)

SEVERITY = {"error": types.DiagnosticSeverity.Error, "warning": types.DiagnosticSeverity.Warning}
KINDS = {
    "node": types.CompletionItemKind.Function,
    "type": types.CompletionItemKind.Struct,
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
    uri = params.text_document.uri
    refresh(uri)
    # Saved transitive dependencies can affect any open modular document.
    # Rebuild their small authoring indexes rather than leaving cached exports
    # and definition locations stale until the importer itself changes.
    for other, analysis in list(state["analyses"].items()):
        if other != uri and analysis.program is not None and analysis.program.imports:
            refresh(other)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    state["analyses"].pop(uri, None)
    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
    )


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
    types.TEXT_DOCUMENT_COMPLETION, types.CompletionOptions(trigger_characters=["@", "`", ")", "."])
)
def on_completion(params: types.CompletionParams) -> types.CompletionList:
    doc = server.workspace.get_text_document(params.text_document.uri)
    items = completions(
        state["analyses"].get(doc.uri), doc.source, params.position.line, params.position.character
    )
    word = word_at(doc.source, params.position.line, params.position.character)
    start = word[1] if word else params.position.character
    replacement = types.Range(
        start=types.Position(line=params.position.line, character=start),
        end=(
            types.Position(line=params.position.line, character=word[2])
            if word
            else params.position
        ),
    )
    return types.CompletionList(
        is_incomplete=False,
        items=[
            types.CompletionItem(
                label=label,
                kind=KINDS[kind],
                text_edit=types.TextEdit(range=replacement, new_text=label),
            )
            for label, kind in items
        ],
    )


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def on_definition(params: types.DefinitionParams) -> types.Location | None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    target = definition_location(
        _analysis(doc.uri),
        doc.source,
        params.position.line,
        params.position.character,
        doc.path,
    )
    if target is None:
        return None
    pos = types.Position(line=target.line, character=0)
    uri = Path(target.path).resolve().as_uri() if target.path else doc.uri
    return types.Location(uri=uri, range=types.Range(start=pos, end=pos))


@server.feature(
    types.TEXT_DOCUMENT_SIGNATURE_HELP, types.SignatureHelpOptions(trigger_characters=["(", ","])
)
def on_signature_help(params: types.SignatureHelpParams) -> types.SignatureHelp | None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    markdown = signature_help(
        _analysis(doc.uri),
        doc.source,
        params.position.line,
        params.position.character,
    )
    if markdown is None or not markdown.startswith("```kir\n"):
        return None
    label = markdown.split("\n", 2)[1]
    return types.SignatureHelp(
        signatures=[
            types.SignatureInformation(
                label=label,
                documentation=types.MarkupContent(kind=types.MarkupKind.Markdown, value=markdown),
            )
        ],
        active_signature=0,
    )


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
