# KohakuNodeIR Language Support for VS Code

Syntax highlighting for `.kir` files (KohakuNodeIR intermediate representation).

## Install (from source)

```bash
cd tree-sitter-kir/vscode
# Option 1: symlink into VS Code extensions
ln -s "$(pwd)" ~/.vscode/extensions/kir-language

# Option 2: package as .vsix
npx @vscode/vsce package
code --install-extension kir-language-0.1.0.vsix
```

## Features

- Syntax highlighting for all KIR constructs
- Comment toggling (`Ctrl+/`)
- Bracket matching and auto-closing
- Code folding for namespaces, `@dataflow:` blocks, `@def` subgraphs
- Indentation rules

## Highlighted elements

| Element | Color |
|---|---|
| `# comments` | green/grey |
| `"strings"`, `` `labels` `` | orange/yellow |
| `42`, `3.14` | cyan/blue |
| `True`, `False`, `None`, `_` | purple |
| `branch`, `switch`, `jump`, `parallel` | red/bold |
| `@meta`, `@dataflow`, `@mode`, `@def` | attribute/gold |
| `func_name` in calls | blue |
| `namespace:` labels | label color |
