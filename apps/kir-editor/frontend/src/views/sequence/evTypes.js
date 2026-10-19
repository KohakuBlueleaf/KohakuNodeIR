/**
 * EV3-style data colours: number yellow, logic green, text orange, anything
 * else grey; and the type a name carries, read from what writes it.
 */

import { flatten } from "@/program/structure"

export const EV_COLOR = {
  number: "#E8B600",
  bool: "#3FA34D",
  text: "#EE7A1F",
  other: "#8F8F8F",
}

export function evKindOfType(type) {
  const head = (type || "").replace(/\?$/, "").split("[")[0]
  if (head === "int" || head === "float") return "number"
  if (head === "bool") return "bool"
  if (head === "str") return "text"
  return "other"
}

export function evKindOfLiteral(v) {
  if (typeof v === "boolean") return "bool"
  if (typeof v === "number") return "number"
  if (typeof v === "string") return "text"
  return "other"
}

/** Name -> EV kind, from assignments of literals and typed call outputs. */
export function nameKinds(tree, resolveCall) {
  const out = new Map()
  const walk = (stmts) => {
    for (const s of stmts) {
      if (s.type === "assign") {
        const k = s.vtype ? evKindOfType(s.vtype) : "lit" in s.value ? evKindOfLiteral(s.value.lit) : out.get(s.value.name)
        if (k && !out.has(s.target)) out.set(s.target, k)
      }
      if (s.type === "call") {
        const sig = resolveCall(s.name)
        s.outs.forEach((o, i) => {
          if (o && !out.has(o)) out.set(o, evKindOfType(sig?.outputs?.[i]?.type))
        })
      }
      if (s.type === "def") for (const p of s.params) if (p.type) out.set(p.name, evKindOfType(p.type))
      for (const k of ["body", "handler"]) if (Array.isArray(s[k])) walk(s[k])
    }
  }
  walk(flatten([...tree.head, ...tree.body]))
  return out
}
