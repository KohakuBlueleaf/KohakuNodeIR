# KIR for VS Code

Editing support for KIR v2 (Kohaku Node IR) `.kir` files. No build step.

- Syntax highlighting (`syntaxes/kir.tmLanguage.json`) with the same token
  classes as `editors/tree-sitter-kir/queries/highlights.scm`:

  | Element | Scope |
  |---|---|
  | `@use @def @meta @hint @mode @dataflow @try @except @typehint` | `keyword.control.directive` |
  | `branch switch jump parallel each collect` | `support.function.builtin` |
  | node names, `@use` prefixes (`g.` in `g.entity`) | `entity.name.function.call`, `entity.name.namespace` |
  | `@def` names | `entity.name.function.definition` |
  | `` `labels` `` and `namespace:` | `entity.name.tag.label` |
  | types (`Image`, `int`, `_`, `?`, `\|`) | `entity.name.type`, `support.type.builtin`, `keyword.operator.type` |
  | strings, numbers, `True False None` | `string.quoted`, `constant.numeric`, `constant.language` |
  | `_` discard | `variable.language.wildcard` |
  | `#` comments, `##` section comments | `comment.line.number-sign`, `comment.block.documentation` |

- Comment toggling, bracket matching and auto-closing (including backticks),
  indentation after a line ending in `:` and dedent on `@except`,
  indentation-based folding.
- Snippets: `branch`, `switch`, `each`, `eachi`, `collect`, `collecti`, `loop` (namespace entered by
  `jump`), `parallel`, `@def`, `@try`, `@dataflow`, `@use`.
- `.kirgraph` files open as JSON.
- Language server client (`extension.js`): on opening a `.kir` file it starts
  the KIR language server over stdio, which provides diagnostics, hover on
  node calls, completion of node names and labels, formatting, and
  go-to-definition for labels and `@def`. Install the server with
  `pip install "kohakunode[lsp]"` (the Rust core ships inside the kohakunode
  wheel). Command palette: **KIR: Restart Language Server**.

## Collect loops

``(items)collect(item[, index], `body`, value -> results)`` captures `value` at
normal body completion, not at loop entry. Use the `collect` / `collecti`
snippets for a body and capture expression. Completion, hover and signature help
explain the deferred capture and final result publication; the arrow `->` is
highlighted separately from the switch arrow `=>`.

The checker diagnoses result-target references inside the body, escaping jumps,
and prohibited global mutations. The CLI/editor pass list includes
`expand_collect`. A Rust-selected language server uses native collect support
when available; an older extension without the syntax emits a warning before
using the Python reference for that document. Rebuild the extension to enable
the native path.

## Record schemas

The language server reads record declarations from **format-2 `.kirsig.json`**
files on `kir.sigPath`; it does not import a library's Python implementation.
For a `Point` schema in library `geometry`, `@use "geometry" as g` exposes
`g.Point.make`, `g.Point.get.x`, and `g.Point.with.x` as ordinary node calls.
Completion and signature help include their derived ports and constructor defaults.
`with` returns an updated record value; it is not an in-place field mutation.

Type completion offers both `g.Point` and canonical `geometry.Point`. Hover on
either annotation shows the schema's fields/defaults and canonical identity;
hover on authored `@def` signatures resolves record aliases without rewriting
source text. Ambiguous unaliased record types are reported rather than silently
selecting one library. No new KIR declaration or field-access syntax is required.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `kir.server.path` | `kir-lsp` | command that starts the server |
| `kir.server.args` | `[]` | extra arguments for that command |
| `kir.sigPath` | `[]` | directories searched for node library signatures, sent as `initializationOptions.sigPath` |
| `kir.core` | `auto` | core for diagnostics and formatting: `rust` or `python`, sent as `initializationOptions.core`; `auto` sends nothing and the server picks (Rust when built, else Python) |

Changing any of them restarts the server.

## Install from source

`npm install` is required first: it fetches `vscode-languageclient`, which the
extension loads at runtime.

```sh
npm install
# link the folder into the extensions directory
ln -s "$(pwd)" ~/.vscode/extensions/kir-language
# or package it
npx @vscode/vsce package
code --install-extension kir-language-0.2.0.vsix
```

## Test the grammar

```sh
npx vscode-tmgrammar-test@0.1.3 -g syntaxes/kir.tmLanguage.json test/syntax.kir
```
