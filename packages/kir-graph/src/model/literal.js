/**
 * KIR literals as the graph JSON holds them: plain JSON values, with tuples as
 * {"tuple": [...]}, string-keyed dicts as {"dict": {...}} and other dicts as
 * {"pairs": [[k, v], ...]}; shown in KIR syntax.
 */

export function formatLiteral(v) {
  if (v === null || v === undefined) return "None"
  if (v === true) return "True"
  if (v === false) return "False"
  if (typeof v === "string") return JSON.stringify(v)
  if (typeof v === "number") return String(v)
  if (Array.isArray(v)) return `[${v.map(formatLiteral).join(", ")}]`
  if (v.tuple) return `(${v.tuple.map(formatLiteral).join(", ")}${v.tuple.length === 1 ? "," : ""})`
  if (v.dict) {
    const items = Object.entries(v.dict).map(([k, x]) => `${JSON.stringify(k)}: ${formatLiteral(x)}`)
    return `{${items.join(", ")}}`
  }
  if (v.pairs) return `{${v.pairs.map(([k, x]) => `${formatLiteral(k)}: ${formatLiteral(x)}`).join(", ")}}`
  return JSON.stringify(v)
}

export function shortLiteral(v, max = 22) {
  const s = formatLiteral(v)
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

/** The kind of a literal: number, bool, text or other. */
export function literalKind(v) {
  if (typeof v === "boolean") return "bool"
  if (typeof v === "number") return "number"
  if (typeof v === "string") return "text"
  return "other"
}
