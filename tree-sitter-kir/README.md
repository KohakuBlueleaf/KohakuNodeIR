# tree-sitter-kir

[Tree-sitter](https://tree-sitter.github.io/) grammar for `.kir` files
(KohakuNodeIR intermediate representation).

## What this provides

- **Grammar** (`grammar.js`) -- full tree-sitter grammar for KIR syntax
- **External scanner** (`src/scanner.c`) -- emits `INDENT`, `DEDENT`, and
  `NEWLINE` tokens for KIR's indentation-based blocks (same approach as
  tree-sitter-python)
- **Highlight queries** (`queries/`) -- syntax highlighting rules
- **VS Code extension** (`vscode/`) -- TextMate grammar for VS Code

## VS Code extension

The `vscode/` subdirectory contains a standalone VS Code language extension with
syntax highlighting, comment toggling, bracket matching, and code folding.

### Install

```bash
# Option 1: symlink (instant, updates with repo)
ln -s "$(pwd)/vscode" ~/.vscode/extensions/kir-language

# Option 2: package as .vsix
cd vscode
npx @vscode/vsce package
code --install-extension kir-language-0.1.0.vsix
```

### Highlighted elements

Keywords (`@meta`, `@dataflow`, `@def`, `@mode`), control flow (`branch`,
`switch`, `jump`, `parallel`), literals, strings, label references, comments,
and function names in calls.

## Building the grammar

```bash
npm install
npm run build    # tree-sitter generate
npm run test     # tree-sitter test
```

Requires [tree-sitter-cli](https://github.com/tree-sitter/tree-sitter/tree/master/cli).

## Grammar overview

KIR is indentation-sensitive. Top-level constructs:

- **Assignments** -- `name = expr`
- **Call statements** -- `(inputs) func_name (outputs)`
- **Namespaces** -- `name:` followed by indented body
- **Subgraph definitions** -- `@def (params) name (outputs):` with body
- **Dataflow blocks** -- `@dataflow:` with body
- **Meta annotations** -- `@meta key=value ...`
- **Mode declarations** -- `@mode dataflow`

Literals: integers (decimal, hex, octal, binary), floats, booleans, None,
strings (single/double/triple-quoted), lists, and dicts.
