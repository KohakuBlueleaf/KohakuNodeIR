/**
 * New statements for the statement views (blocks, sequence), from a palette
 * entry: the same `spec` the graph views receive (`{kind, name?, sig?, use?}`).
 */

import { formatLiteral, parseLiteral } from "@kohaku/kir-graph"

import { fresh, group, usedNames } from "@/program/structure"

/** A literal that fits a type, for a new input slot. */
export function defaultFor(type) {
  const head = (type || "").replace(/\?$/, "").split("[")[0]
  if (head === "int" || head === "float") return 0
  if (head === "str") return ""
  if (head === "bool") return true
  if (head === "list") return []
  return null
}

/** An expression from slot text: a literal when it reads as one, else a name. */
export function exprFromText(text) {
  const t = text.trim()
  if (/^[A-Za-z_]\w*$/.test(t) && !["True", "False", "None"].includes(t)) return { name: t }
  return { lit: parseLiteral(t) }
}

export const exprText = (e) => (e == null ? "" : "name" in e ? e.name : formatLiteral(e.lit))

/** The item a palette entry adds, or null when it adds no statement (a variable read). */
export function itemFor(spec, tree) {
  const names = usedNames(tree)
  const ns = (label) => ({ type: "namespace", label, body: [], line: null })
  switch (spec.kind) {
    case "call": {
      // Required inputs get a slot each; optional ones are left to their defaults.
      const args = (spec.sig?.inputs || [])
        .filter((p) => !("default" in p))
        .map((p) => ({ value: { lit: defaultFor(p.type) }, key: null }))
      const outs = (spec.sig?.outputs || []).map((p) => fresh(names, p.name))
      return { t: "stmt", s: { type: "call", name: spec.name, args, outs, line: null } }
    }
    case "assign":
    case "value":
    case "set":
      return { t: "stmt", s: { type: "assign", target: fresh(names, "x"), value: { lit: 0 }, vtype: null, line: null } }
    case "branch": {
      const s = { type: "branch", cond: { lit: true }, true_label: fresh(names, "yes"), false_label: fresh(names, "no"), line: null }
      return group([s, ns(s.true_label), ns(s.false_label)])[0]
    }
    case "switch": {
      const a = fresh(names, "case0")
      const b = fresh(names, "case1")
      const d = fresh(names, "other")
      const s = { type: "switch", value: { lit: 0 }, cases: [[0, a], [1, b]], default: d, line: null }
      return group([s, ns(a), ns(b), ns(d)])[0]
    }
    case "each": {
      const s = { type: "each", items: { lit: [] }, item: fresh(names, "item"), index: fresh(names, "i"), label: fresh(names, "body"), has_index: true, line: null }
      return group([s, ns(s.label)])[0]
    }
    case "collect": {
      const item = fresh(names, "item")
      const s = { type: "collect", items: { lit: [] }, item, index: fresh(names, "i"), label: fresh(names, "body"), value: { name: item }, target: fresh(names, "results"), has_index: true, line: null }
      return group([s, ns(s.label)])[0]
    }
    case "parallel": {
      const s = { type: "parallel", labels: [fresh(names, "left"), fresh(names, "right")], line: null }
      return group([s, ...s.labels.map(ns)])[0]
    }
    case "try":
      return { t: "try", s: { type: "try", body: [], handler: [], error_name: fresh(names, "err"), line: null }, body: [], handler: [] }
    case "merge": {
      const label = fresh(names, "loop")
      return group([{ type: "jump", label, line: null }, ns(label)])[0]
    }
    default:
      return null
  }
}
