/**
 * Node-view geometry: data enters on the left and leaves on the right. A node
 * is a card: a header with its title, then rows; each row holds at most one
 * port on the left (an input, with its literal when it has one) and one on the
 * right (an output). With control drawn (`exec`), a single way in and out sits
 * in the header and further control ports take rows of their own.
 *
 * Variables and literals are pills: `get x` (output right), `set x` (input
 * left), a literal (output right).
 */

import { shortLiteral } from "../model/literal.js"
import { textWidth } from "./measure.js"
import { makePort } from "./port.js"
import { TERMINAL_MARK, trunkPort } from "./robo.js"

export const HEAD = 30
export const ROW = 24
// The foot holds the heat meter (styles/nodes.css)
const FOOT = 9
const CELL_GAP = 24
const MIN_W = 150
const PILL_H = 26

const TITLE = {
  assign: (n) => (n.role ? `${n.role} value` : "assign"),
  branch: () => "branch",
  switch: () => "switch",
  merge: (n) => (n.props?.label ? `loop ${n.props.label}` : "merge"),
  each: (n) => `each · ${n.props?.label ?? ""}`,
  collect: (n) => `collect · ${n.props?.label ?? ""}`,
  parallel: () => "parallel",
  try: (n) => (n.props?.error_name ? `try · except ${n.props.error_name}` : "try"),
  dataflow: () => "@dataflow",
  join: (n) => `assign ${n.props?.name}`,
  inputs: () => "inputs",
  outputs: () => "outputs",
  start: (n) => `${TERMINAL_MARK[n.label] ?? ""} ${n.label ?? "Start"}`.trim(),
  end: (n) => `${TERMINAL_MARK[n.label] ?? ""} ${n.label ?? "End"}`.trim(),
}

/** The colour family of a node kind: a card's accent. */
export const ACCENT = {
  call: "sapphire",
  defcall: "taaffeite",
  assign: "amber",
  branch: "iolite",
  switch: "iolite",
  merge: "iolite",
  each: "iolite",
  collect: "iolite",
  parallel: "iolite",
  try: "coral",
  dataflow: "aquamarine",
  join: "taaffeite",
  inputs: "sage",
  outputs: "sage",
  start: "sage",
  end: "sage",
}

export function nodeTitle(node) {
  return node.kind === "call" ? node.name : (TITLE[node.kind] || (() => node.kind))(node)
}

/** The namespace label a control output enters, when it enters a named one. */
function armLabel(node, port) {
  const p = node.props || {}
  if (node.kind === "each" || node.kind === "collect") return port === "body" ? p.label : null
  return p.labels?.[port] ?? null
}

/**
 * The label of a merge input: the loop's entry, or where control comes from
 * (the arm it leaves, else the namespace or statement it leaves from); `↺`
 * marks a jump back. `from` is the edge into it ({ node, port, back }).
 */
function mergeInLabel(node, name, from, regions) {
  if (!from) return name
  if (node.props?.label && !from.back && name === "in_0") return "enter"
  const region = regions?.get(from.node.region)
  const where = armLabel(from.node, from.port) ?? region?.label ?? region?.owner?.port ?? nodeTitle(from.node)
  return `${from.back ? "↺" : "←"} ${where}`
}

/**
 * The label of a control port, naming the namespace it enters. `ctx.ctrlFrom`
 * maps `node id|port` of a control input to the edge into it; `ctx.regions`
 * is the model's region map.
 */
export function ctrlLabel(node, dir, name, ctx = {}) {
  const p = node.props || {}
  if (dir === "in") {
    if (name === "next") return "next ⟲"
    return name.startsWith("in_") ? mergeInLabel(node, name, ctx.ctrlFrom?.get(`${node.id}|${name}`), ctx.regions) : name
  }
  switch (node.kind) {
    case "branch":
      return `${name} · ${p.labels?.[name] ?? "?"}`
    case "switch": {
      if (name === "default") return `else · ${p.labels?.default ?? "?"}`
      const i = Number(name.slice("case_".length))
      return `${shortLiteral(p.cases?.[i], 10)} · ${p.labels?.[name] ?? "?"}`
    }
    case "parallel":
      return p.labels?.[name] ?? name
    case "each":
    case "collect":
      return name === "body" ? `body · ${p.label ?? ""}` : "done"
    default:
      return name
  }
}

function inputLabel(p) {
  if (p.label) return p.label
  const name = p.deferred === "body_end" ? `${p.port} (body end)` : p.port
  return "value" in p ? `${name} = ${shortLiteral(p.value, 18)}` : name
}

function outputLabel(p) {
  return p.var && p.var !== p.port ? `${p.port} → ${p.var}` : p.port
}

// A pill bound to the graph's own inputs or outputs (`param`) is a parameter of the graph, not a variable
function pill(node, param = null) {
  if (node.kind === "value") {
    const title = shortLiteral(node.props?.value, 24)
    const w = Math.max(56, textWidth(title, "title") + 36)
    const out = (node.outputs || [])[0] || { port: "value" }
    return { w, h: PILL_H, shape: "pill", variant: "value", title, rows: [], ports: [makePort("data", "out", out, w, PILL_H / 2, "right")] }
  }
  const title = node.props?.name ?? "?"
  const w = Math.max(56, textWidth(title, "title") + 40)
  const ports =
    node.kind === "get"
      ? [makePort("data", "out", (node.outputs || [])[0] || { port: "value" }, w, PILL_H / 2, "right")]
      : [makePort("data", "in", (node.inputs || [])[0] || { port: "value" }, 0, PILL_H / 2, "left")]
  return { w, h: PILL_H, shape: "pill", variant: param ? "param" : node.kind, param, title, rows: [], ports }
}

/**
 * Geometry of one node. `ctx.defNames`: names of the program's `@def` graphs;
 * `ctx.exec`: whether control ports are drawn; `ctx.direction`: the layout's
 * flow ("DOWN" puts control on the top and bottom edges).
 */
export function cardGeometry(node, ctx = {}) {
  if (node.kind === "value" || node.kind === "get" || node.kind === "set") return pill(node, node.param ?? null)
  if (ctx.exec && ctx.direction === "DOWN") return downCard(node, ctx)
  const exec = !!ctx.exec
  const ctrlIn = exec ? node.ctrl_in || [] : []
  const ctrlOut = exec ? node.ctrl_out || [] : []
  const headIn = ctrlIn.includes("in") ? "in" : null
  const headOut = ctrlOut.length === 1 ? ctrlOut[0] : null
  const left = [
    ...ctrlIn.filter((c) => c !== headIn).map((c) => ({ flow: "ctrl", p: c, label: ctrlLabel(node, "in", c, ctx) })),
    ...(node.inputs || []).map((p) => ({ flow: "data", p, label: inputLabel(p), literal: "value" in p })),
  ]
  const right = [
    ...ctrlOut.filter((c) => c !== headOut).map((c) => ({ flow: "ctrl", p: c, label: ctrlLabel(node, "out", c, ctx) })),
    ...(node.outputs || []).map((p) => ({ flow: "data", p, label: outputLabel(p) })),
  ]
  const isDef = node.kind === "call" && ctx.defNames?.has(node.name)
  const title = nodeTitle(node)
  const n = Math.max(left.length, right.length)
  const leftW = Math.max(0, ...left.map((r) => textWidth(r.label)))
  const rightW = Math.max(0, ...right.map((r) => textWidth(r.label)))
  const w = Math.max(MIN_W, textWidth(title, "title") + 56, leftW + rightW + CELL_GAP + 28)
  const h = HEAD + n * ROW + FOOT

  const ports = []
  if (headIn) ports.push(makePort("ctrl", "in", "in", 0, HEAD / 2, "left", { header: true }))
  if (headOut) ports.push(makePort("ctrl", "out", headOut, w, HEAD / 2, "right", { header: true }))
  const rows = []
  for (let i = 0; i < n; i++) {
    const y = HEAD + i * ROW + ROW / 2
    const row = { y }
    const l = left[i]
    const r = right[i]
    if (l) {
      const pt = makePort(l.flow, "in", l.p, 0, y, "left")
      ports.push(pt)
      row.left = { handle: pt.handle, flow: l.flow, label: l.label, literal: !!l.literal }
    }
    if (r) {
      const pt = makePort(r.flow, "out", r.p, w, y, "right")
      ports.push(pt)
      row.right = { handle: pt.handle, flow: r.flow, label: r.label }
    }
    rows.push(row)
  }
  const variant = isDef ? "defcall" : node.kind
  return { w, h, shape: "card", variant, accent: ACCENT[variant] || "sapphire", title, ports, rows, head: HEAD }
}

const CTRL_ROW = 20
const CTRL_SLOT_PAD = 18

/**
 * A card in a layout whose control runs down: the trunk enters at the top
 * centre and leaves at the bottom centre (labelled under the header and over
 * the foot when the port has a name); every other control port (a jump back
 * in, a loop's `done`, an arm that jumps back) takes a labelled row on the
 * right, before the data outputs. Data inputs stay on the left.
 */
function downCard(node, ctx) {
  const ctrlIn = node.ctrl_in || []
  const ctrlOut = node.ctrl_out || []
  const entry = ctrlIn.includes("in") ? "in" : ctrlIn.find((c) => !ctx.ctrlFrom?.get(`${node.id}|${c}`)?.back) ?? ctrlIn[0]
  const exit = ctrlOut.length ? trunkPort(node, ctrlOut, ctx) : null
  const ins = entry ? [{ p: entry, label: entry === "in" ? "" : ctrlLabel(node, "in", entry, ctx) }] : []
  const outs = exit ? [{ p: exit, label: ctrlOut.length > 1 || exit !== "out" ? ctrlLabel(node, "out", exit, ctx) : "" }] : []
  const left = (node.inputs || []).map((p) => ({ p, label: inputLabel(p), literal: "value" in p }))
  const right = [
    ...ctrlIn.filter((c) => c !== entry).map((c) => ({ p: c, flow: "ctrl", dir: "in", label: ctrlLabel(node, "in", c, ctx) })),
    ...ctrlOut.filter((c) => c !== exit).map((c) => ({ p: c, flow: "ctrl", dir: "out", label: ctrlLabel(node, "out", c, ctx) })),
    ...(node.outputs || []).map((p) => ({ p, flow: "data", dir: "out", label: outputLabel(p) })),
  ]
  const isDef = node.kind === "call" && ctx.defNames?.has(node.name)
  const title = nodeTitle(node)
  const slots = (list) => list.reduce((sum, c) => sum + textWidth(c.label) + CTRL_SLOT_PAD, 0)
  const n = Math.max(left.length, right.length)
  const leftW = Math.max(0, ...left.map((r) => textWidth(r.label)))
  const rightW = Math.max(0, ...right.map((r) => textWidth(r.label)))
  const w = Math.max(MIN_W, textWidth(title, "title") + 56, leftW + rightW + CELL_GAP + 28, slots(ins) + 16, slots(outs) + 16)
  const inRow = ins.some((c) => c.label) ? CTRL_ROW : 0
  const outRow = outs.some((c) => c.label) ? CTRL_ROW : 0
  const body = HEAD + inRow
  const h = body + n * ROW + outRow + FOOT

  const ports = []
  const rows = []
  const xs = (list) => {
    const total = slots(list)
    let x = (w - total) / 2
    return list.map((c) => {
      const width = textWidth(c.label) + CTRL_SLOT_PAD
      const at = list.length === 1 ? w / 2 : x + width / 2
      x += width
      return at
    })
  }
  const inX = xs(ins)
  const outX = xs(outs)
  ins.forEach((c, i) => ports.push(makePort("ctrl", "in", c.p, inX[i], 0, "top")))
  outs.forEach((c, i) => ports.push(makePort("ctrl", "out", c.p, outX[i], h, "bottom")))
  const ctrlLabels = [
    ...(inRow ? ins.map((c, i) => ({ x: inX[i], y: HEAD + CTRL_ROW / 2, label: c.label })) : []),
    ...(outRow ? outs.map((c, i) => ({ x: outX[i], y: h - FOOT - CTRL_ROW / 2, label: c.label })) : []),
  ].filter((c) => c.label)
  for (let i = 0; i < n; i++) {
    const y = body + i * ROW + ROW / 2
    const row = { y }
    const l = left[i]
    const r = right[i]
    if (l) {
      const pt = makePort("data", "in", l.p, 0, y, "left")
      ports.push(pt)
      row.left = { handle: pt.handle, flow: "data", label: l.label, literal: !!l.literal }
    }
    if (r) {
      const pt = makePort(r.flow, r.dir, r.p, w, y, "right")
      ports.push(pt)
      row.right = { handle: pt.handle, flow: r.flow, label: r.label }
    }
    rows.push(row)
  }
  const variant = isDef ? "defcall" : node.kind
  return { w, h, shape: "card", variant, accent: ACCENT[variant] || "sapphire", title, ports, rows, ctrlLabels, head: HEAD }
}
