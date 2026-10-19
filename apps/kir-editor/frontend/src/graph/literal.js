/**
 * KIR literals as the graph JSON holds them (graph.md): plain JSON values, with
 * tuples as {"tuple": [...]}, string-keyed dicts as {"dict": {...}} and other
 * dicts as {"pairs": [[k, v], ...]}. These helpers show them in KIR syntax and
 * read them back from what a user types.
 */

export function formatLiteral(v) {
  if (v === null || v === undefined) return "None"
  if (v === true) return "True"
  if (v === false) return "False"
  if (typeof v === "string") return JSON.stringify(v)
  if (typeof v === "number") return String(v)
  if (Array.isArray(v)) return `[${v.map(formatLiteral).join(", ")}]`
  if (v.tuple) return `(${v.tuple.map(formatLiteral).join(", ")}${v.tuple.length === 1 ? "," : ""})`
  if (v.dict)
    return `{${Object.entries(v.dict)
      .map(([k, x]) => `${JSON.stringify(k)}: ${formatLiteral(x)}`)
      .join(", ")}}`
  if (v.pairs) return `{${v.pairs.map(([k, x]) => `${formatLiteral(k)}: ${formatLiteral(x)}`).join(", ")}}`
  return JSON.stringify(v)
}

export function shortLiteral(v, max = 22) {
  const s = formatLiteral(v)
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

/**
 * Parse a literal typed in KIR syntax: None/True/False, numbers, strings,
 * lists, string-keyed dicts. Throws on anything else.
 */
export function parseLiteral(text) {
  const src = text.trim()
  if (src === "None") return null
  if (src === "True") return true
  if (src === "False") return false
  const json = src
    .replace(/\bNone\b/g, "null")
    .replace(/\bTrue\b/g, "true")
    .replace(/\bFalse\b/g, "false")
    .replace(/'([^'\\]*)'/g, (_, s) => JSON.stringify(s))
  const value = JSON.parse(json)
  return encode(value)
}

function encode(v) {
  if (Array.isArray(v)) return v.map(encode)
  if (v && typeof v === "object")
    return { dict: Object.fromEntries(Object.entries(v).map(([k, x]) => [k, encode(x)])) }
  return v
}
