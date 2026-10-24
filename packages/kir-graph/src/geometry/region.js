/** Region boxes and collapsed regions: their titles, padding and the collapsed box's ports. */

import { shortLiteral } from "../model/literal.js"
import { textWidth } from "./measure.js"
import { makePort } from "./port.js"

export const REGION_HEAD = 24
export const REGION_PAD = 12

/** The title a region box shows: what enters it and its label. */
export function regionTitle(region, owner) {
  const label = region.label ?? ""
  const port = region.owner?.port
  const p = owner?.props || {}
  switch (region.kind) {
    case "branch":
      return `${port === "true" ? "if true" : "else"} · ${label}`
    case "switch": {
      if (port === "default") return `default · ${label}`
      return `case ${shortLiteral(p.cases?.[Number(String(port).slice("case_".length))], 12)} · ${label}`
    }
    case "parallel":
      return `parallel · ${label}`
    case "each":
    case "collect": {
      const names = [p.item || "_", ...(p.has_index ? [p.index || "_"] : [])].join(", ")
      return `${region.kind} ${names} · ${label}`
    }
    case "merge":
      return `loop · ${label}`
    case "try":
      return port === "except" ? (p.error_name ? `except ${p.error_name}` : "except") : "try"
    case "dataflow":
      return "@dataflow · ordered by data"
    default:
      return label || region.kind
  }
}

/** The style family of a region box. */
export function regionTone(region) {
  if (region.kind === "try") return region.owner?.port === "except" ? "except" : "try"
  if (region.kind === "merge") return "loop"
  return region.kind
}

export const regionMinWidth = (title) => textWidth(title, "region") + 40

/**
 * A collapsed region: one box standing for every statement inside it. Control
 * enters on the side the flow comes from (top when it runs down, else left),
 * data on the left and right.
 */
export function collapsedGeometry(title, count, direction) {
  const sub = `${count} statement${count === 1 ? "" : "s"}`
  const w = Math.max(150, textWidth(title, "region") + 48, textWidth(sub) + 40)
  const h = 48
  const down = direction === "DOWN"
  const ports = [
    makePort("ctrl", "in", "*", down ? w / 2 : 0, down ? 0 : 12, down ? "top" : "left"),
    makePort("ctrl", "out", "*", down ? w / 2 : w, down ? h : 12, down ? "bottom" : "right"),
    makePort("data", "in", "*", 0, down ? h / 2 : h - 14, "left"),
    makePort("data", "out", "*", w, down ? h / 2 : h - 14, "right"),
  ]
  return { w, h, shape: "collapsed", title, sub, ports }
}
