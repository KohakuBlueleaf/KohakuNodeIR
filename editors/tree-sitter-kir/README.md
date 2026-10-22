# tree-sitter-kir

Tree-sitter grammar for KIR v2 (Kohaku Node IR). It follows
`docs/spec/language.md` and the reference grammar
`src/kohakunode/syntax/kir.lark`.

- `grammar.js` — the grammar; `src/` holds the generated parser and the
  external scanner (`src/scanner.c`) that emits INDENT, DEDENT and NEWLINE as
  zero-width tokens. A tab counts as 4 columns. Line breaks inside `( [ {` are
  whitespace. Comment-only lines never affect indentation; an indented first
  code line, or any unexpected indent, is a parse error.
- Lexical rules follow the reference grammar: the scanner also lexes the
  `@`-directives so they end at a word boundary (`@metax` is an error);
  `True False None _` are reserved and never identifiers, while `_tmp`,
  `Nonesuch`, `Truex`, `asg` are; `None` is accepted as a type; `@meta`/`@hint`
  tuples are `()`, `(x,)`, `(x, y)`; numbers use ASCII digits only.
  The `reserved` grammar field needs tree-sitter-cli 0.25 or newer.
- `queries/highlights.scm` — directives, builtins (`branch switch jump parallel
  each collect`), node names and `@use` prefixes, labels and namespaces, types,
  literals, `##` section comments. The patterns do not overlap, so the result
  is the same in editors where the first match wins and where the last wins.
- Collect captures use a `collect_capture` node with `value` and `target`
  fields for `value -> results` inside the call's output list. The capture arrow
  is an operator; value and target names are variable highlights. Arity and
  collect-body restrictions remain checker responsibilities.
- `queries/folds.scm`, `queries/locals.scm`.
- `test/corpus/` — parse-tree tests, including `:error` cases for every
  lexical rule above; `test/highlight/` — highlight assertions.

## Build and test

```sh
npx tree-sitter-cli@0.27.1 generate
npx tree-sitter-cli@0.27.1 test
npx tree-sitter-cli@0.27.1 parse path/to/file.kir
```

The highlight test uses capture names outside the CLI's default theme
(`label`, `keyword.directive`, `function.call`, ...). Pass a config whose
`theme` lists them (`tree-sitter test --config-path config.json`); the default
theme drops those assertions.

A statement with no line break before the next one (`(a)f(b) (c)g(d)`) is
recovered by inserting a missing NEWLINE. That token is hidden, so the printed
tree shows no `ERROR`/`MISSING` node and `tree-sitter parse --stat` counts the
file as a successful parse. A corpus test marked `:error` does catch it; for
other files, run `tree-sitter parse -d normal` and look for `detect_error` in
the log.
