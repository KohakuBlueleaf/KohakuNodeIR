/**
 * A small CodeMirror stream mode for KIR text (docs/spec/language.md).
 *
 * The one context it tracks is the call form `(inputs)name(outputs)`: the
 * identifier right after a closing `)` is a node name, or a builtin.
 */

import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language"
import { tags as t } from "@lezer/highlight"

const BUILTINS = new Set(["branch", "switch", "jump", "parallel", "each"])
const ATOMS = new Set(["True", "False", "None", "_"])

const kirMode = {
  name: "kir",
  startState: () => ({ afterClose: false, depth: 0 }),
  token(stream, state) {
    if (stream.sol()) state.afterClose = false
    if (stream.eatSpace()) return null
    if (stream.match("##")) {
      stream.skipToEnd()
      return "sectionComment"
    }
    if (stream.peek() === "#") {
      stream.skipToEnd()
      return "comment"
    }
    if (stream.match(/^@[A-Za-z_]\w*/)) return "directive"
    if (stream.match(/^`[^`]*`/)) {
      state.afterClose = false
      return "label"
    }
    if (stream.match(/^("""|''')/)) {
      const quote = stream.current()
      while (!stream.eol()) {
        if (stream.match(quote)) return "string"
        stream.next()
      }
      return "string"
    }
    if (stream.match(/^"(?:[^"\\]|\\.)*"?/) || stream.match(/^'(?:[^'\\]|\\.)*'?/)) return "string"
    if (stream.match(/^(?:0[xob][0-9a-f_]+|\d[\d_]*(?:\.\d*)?(?:e[+-]?\d+)?|\.\d+)/i)) return "number"
    if (stream.match("=>")) return "operator"
    if (stream.sol() || stream.column() === stream.indentation()) {
      if (stream.match(/^[A-Za-z_]\w*(?=:\s*(#.*)?$)/)) return "namespace"
    }
    const ident = stream.match(/^[A-Za-z_][\w.]*/)
    if (ident) {
      const word = ident[0]
      const call = state.afterClose
      state.afterClose = false
      if (call) return BUILTINS.has(word) ? "builtin" : "node"
      if (ATOMS.has(word)) return "atom"
      if (stream.match(/^\s*(?::[^=]*)?=(?!=|>)/, false) && stream.column() === stream.indentation())
        return "definition"
      return "name"
    }
    const ch = stream.next()
    if (ch === ")") {
      state.depth = Math.max(0, state.depth - 1)
      state.afterClose = state.depth === 0
      return "paren"
    }
    state.afterClose = false
    if (ch === "(") {
      state.depth++
      return "paren"
    }
    return "punct"
  },
  tokenTable: {
    sectionComment: t.heading,
    comment: t.lineComment,
    directive: t.meta,
    label: t.labelName,
    string: t.string,
    number: t.number,
    operator: t.operator,
    namespace: t.definition(t.labelName),
    builtin: t.controlKeyword,
    node: t.function(t.variableName),
    atom: t.atom,
    definition: t.definition(t.variableName),
    name: t.variableName,
    paren: t.paren,
    punct: t.punctuation,
  },
}

export const kirLanguage = StreamLanguage.define(kirMode)

// Colours from the gem palette, through CSS variables set per theme (code.css).
export const kirHighlight = HighlightStyle.define([
  { tag: t.heading, color: "var(--kir-code-section)", fontWeight: "600" },
  { tag: t.lineComment, color: "var(--kir-code-comment)", fontStyle: "italic" },
  { tag: t.meta, color: "var(--kir-code-directive)" },
  { tag: t.labelName, color: "var(--kir-code-label)" },
  { tag: t.definition(t.labelName), color: "var(--kir-code-label)", fontWeight: "600" },
  { tag: t.string, color: "var(--kir-code-string)" },
  { tag: t.number, color: "var(--kir-code-number)" },
  { tag: t.atom, color: "var(--kir-code-number)" },
  { tag: t.operator, color: "var(--kir-code-label)" },
  { tag: t.controlKeyword, color: "var(--kir-code-builtin)", fontWeight: "600" },
  { tag: t.function(t.variableName), color: "var(--kir-code-node)", fontWeight: "600" },
  { tag: t.definition(t.variableName), color: "var(--kir-code-def)" },
  { tag: [t.paren, t.punctuation], color: "var(--kir-code-punct)" },
])

export const kir = () => [kirLanguage, syntaxHighlighting(kirHighlight)]
