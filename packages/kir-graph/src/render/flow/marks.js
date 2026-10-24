/** What every drawn element shows the same way: selection and overlay classes, tooltips. */

import { sameName } from "../overlay.js"

/** Classes of an element: selected, hovered, of the variable in focus, heated, and its overlay status. */
export function markClasses(state, key, id, entry, node = null) {
  const sel = state.selected.value
  return {
    "is-selected": sel != null && (sel === key || sel === id),
    "is-hovered": state.hovered.value != null && state.hovered.value === key,
    "is-same": sameName(state, node),
    "is-hot": entry?.heat != null,
    [`is-${entry?.status}`]: !!entry?.status,
  }
}

/** A node's tooltip: kind, id, source path and line, hints. */
export function nodeTooltip(node) {
  const lines = [`${node.kind} · ${node.id}`]
  if (node.path) lines.push(`path ${node.path}`)
  const o = node.origin
  if (o) lines.push(`${o.module}${o.line != null ? `:${o.line}` : ""}${o.definition ? ` in ${o.definition}` : ""}`)
  const hints = Object.entries(node.hints || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`)
  if (hints.length) lines.push(`@hint ${hints.join(" ")}`)
  return lines.join("\n")
}
