/**
 * What the statement views write for an item: its title, its argument slots
 * with their port names, the names it binds, and the header of each arm.
 */

import { inputExpr, outputNames } from "../../model/graph.js"
import { shortLiteral } from "../../model/literal.js"

/** `[{label, expr, type}]`: each input of a node with what it reads. */
export function slots(model, node) {
  return (node.inputs || []).map((p) => ({
    label: p.deferred === "body_end" ? `${p.port} (body end)` : p.port,
    keyword: !!p.keyword,
    type: p.type || null,
    expr: inputExpr(model, node, p.port),
  }))
}

/** `[{port, name}]`: each output and the name it binds (`null`: discarded). */
export function binds(model, node) {
  const names = outputNames(model, node)
  return (node.outputs || []).map((p, i) => ({ port: p.port, type: p.type || null, name: names[i] }))
}

export function itemTitle(model, it) {
  const n = it.node
  switch (it.t) {
    case "loop":
      return `loop ${n.props?.label ?? ""}`
    case "try":
      return n.props?.error_name ? `try · except ${n.props.error_name}` : "try"
    case "dataflow":
      return "dataflow · in data order"
  }
  switch (n.kind) {
    case "call":
      return n.name
    case "assign":
      return "set"
    case "each":
    case "collect": {
      const p = n.props || {}
      const names = [p.item || "_", ...(p.has_index ? [p.index || "_"] : [])].join(", ")
      return `${n.kind === "collect" ? "collect" : "for each"} ${names} in`
    }
    case "inputs":
      return `define ${model.name}`
    case "outputs":
      return "return"
    default:
      return n.kind
  }
}

/** The header of arm `i` of a group or try item. */
export function armTitle(it, i) {
  const n = it.node
  const r = it.arms[i].region
  const p = n.props || {}
  const port = r.owner?.port
  switch (n.kind) {
    case "branch":
      return port === "true" ? "then" : "else"
    case "switch":
      if (port === "default") return "default"
      return `case ${shortLiteral(p.cases?.[Number(String(port).slice("case_".length))], 14)}`
    case "parallel":
      return "arm"
    case "each":
    case "collect":
      return "do"
    case "try":
      return port === "except" ? (p.error_name ? `except ${p.error_name}` : "except") : "try"
    default:
      return port ?? ""
  }
}

/** The colour family of an item, as the node view's card accents. */
export function itemTone(model, it) {
  if (it.t === "try") return "coral"
  if (it.t === "dataflow") return "aquamarine"
  if (it.t !== "stmt") return "iolite"
  const n = it.node
  if (n.kind === "assign") return "amber"
  if (n.kind === "inputs" || n.kind === "outputs") return "sage"
  if (n.kind === "call" && model.defNames.has(n.name)) return "taaffeite"
  return n.kind === "call" ? "sapphire" : "iolite"
}
