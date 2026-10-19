# KIR for VS Code

Editing support for KIR v2 (Kohaku Node IR) `.kir` files. No build step.

- Syntax highlighting (`syntaxes/kir.tmLanguage.json`) with the same token
  classes as `editors/tree-sitter-kir/queries/highlights.scm`:

  | Element | Scope |
  |---|---|
  | `@use @def @meta @hint @mode @dataflow @try @except @typehint` | `keyword.control.directive` |
  | `branch switch jump parallel each` | `support.function.builtin` |
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
- Snippets: `branch`, `switch`, `each`, `eachi`, `loop` (namespace entered by
  `jump`), `parallel`, `@def`, `@try`, `@dataflow`, `@use`.
- `.kirgraph` files open as JSON.
- Language server client (`extension.js`): on opening a `.kir` file it starts
  the KIR language server over stdio, which provides diagnostics, hover on
  node calls, completion of node names and labels, formatting, and
  go-to-definition for labels and `@def`. Install the server with
  `pip install "kohakunode[lsp]"` (the Rust core ships inside the kohakunode
  wheel). Command palette: **KIR: Restart Language Server**.

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
