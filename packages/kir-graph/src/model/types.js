/**
 * Wire colours by type, as CSS variables of the theme (tokens.css): literal
 * types have fixed gems, nominal types hash onto the gem shadows, untyped is
 * the neutral. Control is iolite.
 */

export const CTRL = "var(--kg-ctrl)"
export const UNTYPED = "var(--kg-untyped)"

const FIXED = {
  int: "var(--kg-type-int)",
  float: "var(--kg-type-float)",
  str: "var(--kg-type-str)",
  bool: "var(--kg-type-bool)",
  list: "var(--kg-type-list)",
  dict: "var(--kg-type-dict)",
  None: UNTYPED,
}

const NOMINAL = 8

/** The head name of a type text: `list[Box]` -> list, `Node?` -> Node, `A | B` -> A. */
export function typeHead(type) {
  if (!type || type === "_") return null
  const m = /^\s*([A-Za-z_][\w.]*)/.exec(type)
  return m ? m[1] : null
}

export function typeColor(type) {
  const head = typeHead(type)
  if (!head) return UNTYPED
  if (FIXED[head]) return FIXED[head]
  let h = 0
  for (const ch of head) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return `var(--kg-type-nominal-${h % NOMINAL})`
}

/** The sequence view's kind of a type: number, bool, text or other. */
export function typeKind(type) {
  const head = typeHead(type)
  if (head === "int" || head === "float") return "number"
  if (head === "bool") return "bool"
  if (head === "str") return "text"
  return "other"
}
