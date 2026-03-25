/**
 * KIR language definition for Monaco editor.
 * Registers syntax highlighting with Monarch tokenizer and a Catppuccin-based dark theme.
 */

import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

// Monaco requires a global environment for web workers in Vite/ESM builds
self.MonacoEnvironment = {
  getWorker() {
    return new editorWorker()
  },
}

let registered = false

export function registerKirLanguage(monaco) {
  if (registered) return
  registered = true

  monaco.languages.register({ id: 'kir' })

  monaco.languages.setMonarchTokensProvider('kir', {
    defaultToken: 'identifier',

    directives: ['@meta', '@mode', '@def', '@dataflow'],
    keywords: ['branch', 'switch', 'jump', 'parallel'],
    constants: ['True', 'False', 'None'],

    tokenizer: {
      root: [
        // Triple-quoted strings (must come before single-quoted)
        [/'''/, 'string', '@tripleStringSingle'],
        [/"""/, 'string', '@tripleStringDouble'],

        // Comments
        [/#.*$/, 'comment'],

        // Directives
        [/@(meta|mode|def|dataflow)\b/, 'keyword.directive'],

        // Label refs (backtick-quoted)
        [/`[^`]*`/, 'variable.label'],

        // Strings
        [/'[^']*'/, 'string'],
        [/"[^"]*"/, 'string'],

        // Numbers: hex, octal, binary, float, int
        [/0[xX][0-9a-fA-F]+/, 'number.hex'],
        [/0[oO][0-7]+/, 'number.octal'],
        [/0[bB][01]+/, 'number.binary'],
        [/\d+\.\d*([eE][-+]?\d+)?/, 'number.float'],
        [/\d+([eE][-+]?\d+)?/, 'number'],

        // Function call pattern: )funcname(
        [/(\))(\w+)(\()/, ['delimiter', 'entity.name.function', 'delimiter']],

        // Constants
        [/\b(True|False|None)\b/, 'constant.language'],

        // Keywords
        [/\b(branch|switch|jump|parallel)\b/, 'keyword.control'],

        // Namespace labels (word followed by colon at line start-ish)
        [/^\s*\w+:/, 'variable.label'],

        // Identifiers
        [/\w+/, 'identifier'],

        // Delimiters
        [/[(),:=]/, 'delimiter'],
      ],

      tripleStringSingle: [
        [/'''/, 'string', '@pop'],
        [/./, 'string'],
      ],

      tripleStringDouble: [
        [/"""/, 'string', '@pop'],
        [/./, 'string'],
      ],
    },
  })

  monaco.editor.defineTheme('kir-catppuccin', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '585b70', fontStyle: 'italic' },
      { token: 'keyword.directive', foreground: 'f5c2e7' },
      { token: 'keyword.control', foreground: 'cba6f7' },
      { token: 'string', foreground: 'a6e3a1' },
      { token: 'number', foreground: 'fab387' },
      { token: 'number.hex', foreground: 'fab387' },
      { token: 'number.octal', foreground: 'fab387' },
      { token: 'number.binary', foreground: 'fab387' },
      { token: 'number.float', foreground: 'fab387' },
      { token: 'variable.label', foreground: '89dceb' },
      { token: 'entity.name.function', foreground: '89b4fa' },
      { token: 'constant.language', foreground: 'fab387' },
      { token: 'identifier', foreground: 'cdd6f4' },
      { token: 'delimiter', foreground: '6c7086' },
    ],
    colors: {
      'editor.background': '#1e1e2e',
      'editor.foreground': '#cdd6f4',
      'editor.lineHighlightBackground': '#313244',
      'editor.selectionBackground': '#45475a',
      'editorCursor.foreground': '#f5e0dc',
      'editorLineNumber.foreground': '#6c7086',
      'editorLineNumber.activeForeground': '#cdd6f4',
    },
  })
}
