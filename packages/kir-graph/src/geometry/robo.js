/**
 * Flowchart geometry (ROBO Pro style): outline shape, port positions and text
 * placement of every element. Program flow runs top (in) to bottom (out);
 * data pins sit on the left (in) and right (out). An `each` element takes its
 * `next` flow on the right, where the body returns. Variables are VAR
 * elements beside the flow; an assignment is an "= value" command.
 */

import { shortLiteral } from "../model/literal.js"
import { textWidth } from "./measure.js"
import { makePort, spread } from "./port.js"

export const HEAD = 26
export const ROW = 20
const FOOT = 16

const dataPort = (dir, p, x, y) => makePort("data", dir, p, x, y, dir === "in" ? "left" : "right")
const ctrlPort = (dir, name, x, y, side = dir === "in" ? "top" : "bottom", extra = {}) =>
  makePort("ctrl", dir, name, x, y, side, extra)

function inputLabel(p) {
  if (p.label) return p.label
  const name = p.deferred === "body_end" ? `${p.port} (body end)` : p.port
  if ("value" in p) return `${name} = ${shortLiteral(p.value, 16)}`
  return p.type ? `${name}: ${p.type}` : name
}

function outputLabel(p) {
  const head = p.var && p.var !== p.port ? `${p.port} → ${p.var}` : p.port
  return p.type ? `${head}: ${p.type}` : head
}

// ---------------------------------------------------------------- work, io, try, each

const RECT_TITLE = {
  inputs: () => "inputs",
  outputs: () => "outputs",
  try: (n) => (n.props?.error_name ? `@try · except ${n.props.error_name}` : "@try"),
  each: (n) => {
    const p = n.props || {}
    const names = [p.item || "_", ...(p.has_index ? [p.index || "_"] : [])].join(", ")
    return `each ${names} in \`${p.label}\``
  },
  collect: (n) => `collect → ${n.props?.target || "results"}`,
  dataflow: () => "@dataflow",
  join: (n) => `assign ${n.props?.name}`,
}

const RECT_SHAPE = { inputs: "io", outputs: "io", try: "try", each: "each", collect: "each", dataflow: "work", join: "join" }
const CTRL_OUT_LABEL = { try: ["try", "except"], each: ["body", "done"], collect: ["body", "done"] }

function rectGeometry(node, ctx) {
  const ins = node.inputs || []
  const outs = node.outputs || []
  const looping = node.kind === "each" || node.kind === "collect"
  const title = node.kind === "call" ? node.name : (RECT_TITLE[node.kind] || (() => node.kind))(node)
  const inLabels = ins.map(inputLabel)
  const outLabels = outs.map(outputLabel)
  if (looping) outLabels.push("next ⟲")
  const rows = Math.max(ins.length, outLabels.length)
  const ctrlIn = (node.ctrl_in || []).filter((p) => !(looping && p === "next"))
  const ctrlOut = node.ctrl_out || []
  // The way out that continues the trunk (a loop's body, a try's body) leaves from the bottom
  // centre; every other (done, except) leaves from the right, labelled beside it
  const mainOut = ctrlOut.length ? trunkPort(node, ctrlOut, ctx) : null
  const sideOuts = ctrlOut.filter((p) => p !== mainOut)
  const footed = ctrlOut.length > 1
  const labelOf = (p) => (CTRL_OUT_LABEL[node.kind] || ctrlOut)[ctrlOut.indexOf(p)] ?? p
  const footLabels = [mainOut, ...sideOuts].filter(Boolean).map(labelOf)
  const maxIn = Math.max(0, ...inLabels.map((s) => textWidth(s)))
  const maxOut = Math.max(0, ...outLabels.map((s) => textWidth(s)))
  const footW = footed ? 2 * Math.max(...footLabels.map((s) => textWidth(s))) + 48 : 0
  const w = Math.max(140, textWidth(title, "title") + 32, maxIn + maxOut + 44, footW)
  const h = HEAD + rows * ROW + (footed ? FOOT : 0) + 6

  const ports = []
  const texts = [{ text: title, x: 10, y: 17, anchor: "start", cls: "title" }]
  ins.forEach((p, i) => {
    const y = HEAD + i * ROW + ROW / 2
    ports.push(dataPort("in", p, 0, y))
    texts.push({ text: inLabels[i], x: 10, y: y + 4, anchor: "start", cls: "value" in p ? "value" : "port" })
  })
  outs.forEach((p, i) => {
    const y = HEAD + i * ROW + ROW / 2
    ports.push(dataPort("out", p, w, y))
    texts.push({ text: outLabels[i], x: w - 10, y: y + 4, anchor: "end", cls: "port" })
  })
  if (looping) {
    const y = HEAD + outs.length * ROW + ROW / 2
    ports.push(ctrlPort("in", "next", w, y, "right"))
    texts.push({ text: "next ⟲", x: w - 10, y: y + 4, anchor: "end", cls: "ctrl" })
  }
  spread(ctrlIn.length, 0, w).forEach((x, i) => ports.push(ctrlPort("in", ctrlIn[i], x, 0)))
  if (mainOut) {
    ports.push(ctrlPort("out", mainOut, w / 2, h))
    if (footed) texts.push({ text: footLabels[0], x: w / 2, y: h - 6, anchor: "middle", cls: "ctrl" })
  }
  sideOuts.forEach((p, i) => {
    const y = h - 8 - i * 14
    ports.push(ctrlPort("out", p, w, y, "right"))
    texts.push({ text: footLabels[i + 1], x: w - 10, y: y + 4, anchor: "end", cls: "ctrl" })
  })
  let shape = RECT_SHAPE[node.kind] || "work"
  if (node.kind === "call" && ctx.defNames?.has(node.name)) shape = "defcall"
  return { w, h, shape, ports, texts, head: HEAD }
}

// ---------------------------------------------------------------- literals, variables, start / end

function valueGeometry(node) {
  const out = (node.outputs || [])[0] || { port: "value" }
  const text = shortLiteral(node.props?.value, 26)
  const w = Math.max(56, textWidth(text) + 30)
  const h = 26
  return {
    w,
    h,
    shape: "value",
    ports: [dataPort("out", out, w, h / 2)],
    texts: [{ text, x: w / 2 - 3, y: h / 2 + 4, anchor: "middle", cls: "pill" }],
  }
}

// A variable is a VAR box; a parameter of the graph itself (`node.param`: "input" | "output") is a flag
function variableGeometry(node) {
  const name = node.props?.name ?? "?"
  const param = node.param ?? null
  const flag = param ? 12 : 0
  const w = Math.max(72, textWidth(name, "title") + 34 + flag)
  const h = 40
  const ports =
    node.kind === "set"
      ? [dataPort("in", (node.inputs || [])[0] || { port: "value" }, 0, h / 2)]
      : [dataPort("out", (node.outputs || [])[0] || { port: "value" }, w, h / 2)]
  const cx = param === "output" ? (w + flag) / 2 : (w - flag) / 2
  return {
    w,
    h,
    shape: param ? "flag" : "variable",
    param,
    ports,
    texts: [
      { text: param ? param.toUpperCase() : "VAR", x: cx, y: 14, anchor: "middle", cls: "muted" },
      { text: name, x: cx, y: 30, anchor: "middle", cls: "title" },
    ],
  }
}

function assignGeometry(node) {
  const input = (node.inputs || [])[0] || { port: "value" }
  const out = (node.outputs || [])[0] || { port: "value" }
  // `role`: an initial or final value of the graph's own data (layout/io.js)
  const text = node.role ? `${node.role} value` : `= ${"value" in input ? shortLiteral(input.value, 18) : "◂"}`
  const label = out.var ? `→ ${out.var}` : ""
  const w = Math.max(96, textWidth(text, "title") + textWidth(label) + 48)
  const h = 34
  return {
    w,
    h,
    shape: "pentagon",
    ports: [
      dataPort("in", input, 0, h / 2),
      dataPort("out", out, w, h / 2),
      ...(node.ctrl_in || []).map((p) => ctrlPort("in", p, (w - 16) / 2, 0)),
      ...(node.ctrl_out || []).map((p) => ctrlPort("out", p, (w - 16) / 2, h)),
    ],
    texts: [
      { text, x: 12, y: h / 2 + 4, anchor: "start", cls: "title" },
      ...(label ? [{ text: label, x: w - 22, y: h / 2 + 4, anchor: "end", cls: "port" }] : []),
    ],
  }
}

export const TERMINAL_MARK = { Start: "▶", End: "■", Entry: "⤵", Exit: "⤴" }

// Start / End of the main graph, Entry / Exit of a `@def` (layout/io.js)
function terminalGeometry(node) {
  const start = node.kind === "start"
  const label = node.label ?? (start ? "Start" : "End")
  const text = `${TERMINAL_MARK[label] ?? ""} ${label}`.trim()
  const w = Math.max(86, textWidth(text, "title") + 36)
  const h = 30
  return {
    w,
    h,
    shape: node.kind,
    ports: start ? (node.ctrl_out || ["out"]).map((p) => ctrlPort("out", p, w / 2, h)) : (node.ctrl_in || ["in"]).map((p) => ctrlPort("in", p, w / 2, 0)),
    texts: [{ text, x: w / 2, y: h / 2 + 4, anchor: "middle", cls: "terminal" }],
  }
}

// ---------------------------------------------------------------- branch, switch, merge, parallel

/**
 * The way out of a branching element that continues the trunk: the first of
 * `ports` that does not jump back (`ctx.backOut` holds `node id|port` of jumps).
 */
export function trunkPort(node, ports, ctx = {}) {
  return ports.find((p) => !ctx.backOut?.has(`${node.id}|${p}`)) ?? ports[0]
}

// The box is the diamond, ports on its corners: the trunk's arm leaves from the
// bottom, the other from the right; arm names ride on the wires (`tailLabel`)
function branchGeometry(node, ctx) {
  const cond = (node.inputs || [])[0] || { port: "cond" }
  const text = "value" in cond ? shortLiteral(cond.value, 10) : "branch"
  const w = Math.round(Math.max(112, 2 * textWidth(text, "title") + 28) / 2) * 2
  const h = 60
  const down = trunkPort(node, ["true", "false"], ctx)
  const side = down === "true" ? "false" : "true"
  return {
    w,
    h,
    shape: "diamond",
    ports: [
      dataPort("in", cond, 0, h / 2),
      ...(node.ctrl_in || []).map((p) => ctrlPort("in", p, w / 2, 0)),
      ctrlPort("out", down, w / 2, h),
      ctrlPort("out", side, w, h / 2, "right"),
    ],
    texts: [{ text, x: w / 2, y: h / 2 + 4, anchor: "middle", cls: "title" }],
  }
}

/** The name an arm's wire carries from a branching element, or null. */
export function tailLabel(node, port) {
  if (node?.kind !== "branch") return null
  const label = node.props?.labels?.[port]
  return `${port === "true" ? "T" : "F"}${label ? ` · ${label}` : ""}`
}

function switchGeometry(node) {
  const props = node.props || {}
  const outs = node.ctrl_out || []
  const labelOf = (port) => {
    const label = props.labels?.[port] ?? "?"
    if (port === "default") return `_ → ${label}`
    return `${shortLiteral(props.cases?.[Number(port.slice("case_".length))], 8)} → ${label}`
  }
  const labels = outs.map(labelOf)
  const slot = Math.max(64, ...labels.map((s) => textWidth(s) + 14))
  const w = Math.max(150, outs.length * slot + 32)
  const h = 58
  const value = (node.inputs || [])[0] || { port: "value" }
  const xs = spread(outs.length, 16, w - 16)
  return {
    w,
    h,
    shape: "hexagon",
    ports: [
      dataPort("in", value, 0, h / 2),
      ...(node.ctrl_in || []).map((p) => ctrlPort("in", p, w / 2, 0)),
      ...outs.map((p, i) => ctrlPort("out", p, xs[i], h)),
    ],
    texts: [
      { text: "value" in value ? `switch ${shortLiteral(value.value, 10)}` : "switch", x: w / 2, y: 20, anchor: "middle", cls: "title" },
      ...labels.map((text, i) => ({ text, x: xs[i], y: h - 9, anchor: "middle", cls: "ctrl" })),
    ],
  }
}

function mergeGeometry(node) {
  const ins = node.ctrl_in || []
  const label = node.props?.label
  const text = label ? `⟲ \`${label}\`` : "merge"
  const w = Math.max(label ? textWidth(text) + 44 : 64, ins.length * 26 + 16)
  const h = label ? 36 : 30
  const xs = spread(ins.length, 6, w - 6)
  return {
    w,
    h,
    shape: "funnel",
    ports: [...ins.map((p, i) => ctrlPort("in", p, xs[i], 0)), ...(node.ctrl_out || []).map((p) => ctrlPort("out", p, w / 2, h))],
    texts: [{ text, x: w / 2, y: h / 2 + 3, anchor: "middle", cls: label ? "loop" : "muted" }],
  }
}

function parallelGeometry(node) {
  const outs = node.ctrl_out || []
  const labels = outs.map((p) => `\`${node.props?.labels?.[p] ?? p}\``)
  const slot = Math.max(56, ...labels.map((s) => textWidth(s) + 16))
  const w = Math.max(120, outs.length * slot + 24)
  const h = 24
  const xs = spread(outs.length, 12, w - 12)
  return {
    w,
    h,
    shape: "bar",
    ports: [...(node.ctrl_in || []).map((p) => ctrlPort("in", p, w / 2, 0)), ...outs.map((p, i) => ctrlPort("out", p, xs[i], h))],
    texts: labels.map((text, i) => ({ text, x: xs[i], y: h / 2 + 4, anchor: "middle", cls: "bar" })),
  }
}

/** Geometry of one element. `ctx.defNames`: names of the program's `@def` graphs. */
export function roboGeometry(node, ctx = {}) {
  switch (node.kind) {
    case "value":
      return valueGeometry(node)
    case "get":
    case "set":
      return variableGeometry(node)
    case "assign":
      return assignGeometry(node)
    case "start":
    case "end":
      return terminalGeometry(node)
    case "branch":
      return branchGeometry(node, ctx)
    case "switch":
      return switchGeometry(node)
    case "merge":
      return mergeGeometry(node)
    case "parallel":
      return parallelGeometry(node)
    default:
      return rectGeometry(node, ctx)
  }
}

/** SVG path of an element's outline in its own box, for the polygon shapes. */
export function shapePath(g) {
  const { w, h } = g
  switch (g.shape) {
    case "pentagon":
      return `M 0 0 L ${w - 16} 0 L ${w} ${h / 2} L ${w - 16} ${h} L 0 ${h} Z`
    case "diamond":
      return `M ${w / 2} 0 L ${w} ${h / 2} L ${w / 2} ${h} L 0 ${h / 2} Z`
    // An input points right, where its wire leaves; an output points left, where its wire comes in
    case "flag":
      return g.param === "output"
        ? `M 12 0 L ${w} 0 L ${w} ${h} L 12 ${h} L 0 ${h / 2} Z`
        : `M 0 0 L ${w - 12} 0 L ${w} ${h / 2} L ${w - 12} ${h} L 0 ${h} Z`
    case "hexagon":
      return `M 0 ${h / 2} L 14 0 L ${w - 14} 0 L ${w} ${h / 2} L ${w - 14} ${h} L 14 ${h} Z`
    case "funnel":
      return `M 0 0 L ${w} 0 L ${w * 0.66} ${h} L ${w * 0.34} ${h} Z`
    default:
      return null
  }
}
