/**
 * Node geometry: size, outline shape, port positions and text placement for
 * every node kind. ELK lays nodes out with exactly these port positions and
 * the node component draws handles at the same points, so routed wires meet
 * their ports.
 *
 * Two axes: control ports sit on the top (in) and bottom (out) edges, data
 * ports on the left (in) and right (out) sides. The one exception is an
 * `each` node's `next` control input, on the right, where the loop body
 * returns.
 */

import { CTRL_COLOR, typeColor } from "@/graph/types"
import { shortLiteral } from "@/graph/literal"

export const ROW = 20
export const HEAD = 26
const FOOT = 16
const CHAR = 6.6 // 11px monospace advance
const TITLE_CHAR = 7.2 // 12px monospace advance

export const tw = (s, char = CHAR) => Math.ceil(String(s).length * char)

/** Handle id of a port: `<flow>:<dir>:<name>`. */
export const handleId = (flow, dir, name) => `${flow}:${dir}:${name}`

export function parseHandle(id) {
  const [flow, dir, ...rest] = id.split(":")
  return { flow, dir, name: rest.join(":") }
}

/** The free `in_<n>` slot a merge offers for one more incoming path. */
export const mergeSlot = (node) => `in_${(node.ctrl_in || []).length}`

function spread(n, from, to) {
  if (n <= 0) return []
  const step = (to - from) / n
  return Array.from({ length: n }, (_, i) => from + step * (i + 0.5))
}

function dataPort(dir, p, x, y) {
  return {
    handle: handleId("data", dir, p.port),
    name: p.port,
    flow: "data",
    dir,
    side: dir === "in" ? "left" : "right",
    x,
    y,
    type: p.type || null,
    color: typeColor(p.type),
  }
}

function ctrlPort(dir, name, x, y, side = dir === "in" ? "top" : "bottom", extra = {}) {
  return {
    handle: handleId("ctrl", dir, name),
    name,
    flow: "ctrl",
    dir,
    side,
    x,
    y,
    color: CTRL_COLOR,
    ...extra,
  }
}

function inputLabel(p) {
  if ("value" in p) return `${p.port} = ${shortLiteral(p.value, 16)}`
  return p.type ? `${p.port}: ${p.type}` : p.port
}

function outputLabel(p) {
  const head = p.var && p.var !== p.port ? `${p.port} → ${p.var}` : p.port
  return p.type ? `${head}: ${p.type}` : head
}

// ---------------------------------------------------------------- rect family

const RECT_TITLE = {
  inputs: () => "inputs",
  outputs: () => "outputs",
  set: (n) => `set ${n.props?.name ?? ""}`,
  try: (n) => (n.props?.error_name ? `@try · except ${n.props.error_name}` : "@try"),
  each: (n) => {
    const p = n.props || {}
    const names = [p.item || "_", ...(p.has_index ? [p.index || "_"] : [])].join(", ")
    return `each ${names} in \`${p.label}\``
  },
}

const RECT_SHAPE = { inputs: "io", outputs: "io", set: "set", try: "try", each: "each" }

const CTRL_OUT_LABEL = { try: ["try", "except"], each: ["body", "done"] }

function rectGeometry(node, ctx) {
  const ins = node.inputs || []
  const outs = node.outputs || []
  const isEach = node.kind === "each"
  const title =
    node.kind === "call" ? node.name : (RECT_TITLE[node.kind] || (() => node.kind))(node)
  const inLabels = ins.map(inputLabel)
  const outLabels = outs.map(outputLabel)
  if (isEach) outLabels.push("next ⟲")
  const rows = Math.max(ins.length, outLabels.length)
  const ctrlIn = (node.ctrl_in || []).filter((p) => !(isEach && p === "next"))
  const ctrlOut = node.ctrl_out || []
  const footed = ctrlOut.length > 1
  const maxIn = Math.max(0, ...inLabels.map((s) => tw(s)))
  const maxOut = Math.max(0, ...outLabels.map((s) => tw(s)))
  const footW = footed ? ctrlOut.length * (Math.max(...ctrlOut.map((s) => tw(s))) + 24) : 0
  const w = Math.max(150, tw(title, TITLE_CHAR) + 36, maxIn + maxOut + 44, footW)
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
  if (isEach) {
    const y = HEAD + outs.length * ROW + ROW / 2
    ports.push(ctrlPort("in", "next", w, y, "right"))
    texts.push({ text: "next ⟲", x: w - 10, y: y + 4, anchor: "end", cls: "ctrl" })
  }
  spread(ctrlIn.length, 0, w).forEach((x, i) => ports.push(ctrlPort("in", ctrlIn[i], x, 0)))
  const outXs = spread(ctrlOut.length, 0, w)
  outXs.forEach((x, i) => {
    ports.push(ctrlPort("out", ctrlOut[i], x, h))
    if (footed)
      texts.push({
        text: (CTRL_OUT_LABEL[node.kind] || ctrlOut)[i] ?? ctrlOut[i],
        x,
        y: h - 6,
        anchor: "middle",
        cls: "ctrl",
      })
  })
  let shape = RECT_SHAPE[node.kind] || "work"
  if (node.kind === "call" && ctx.defNames?.has(node.name)) shape = "defcall"
  if (node.kind === "set" && node.props?.copy) shape = "set"
  return { w, h, shape, ports, texts, head: HEAD }
}

// ---------------------------------------------------------------- pills

function pillGeometry(node) {
  const out = (node.outputs || [])[0]
  let text
  if (node.kind === "get") text = `get ${node.props?.name ?? ""}`
  else {
    const name = out?.var || `${node.id}_value`
    text = `${name}${out?.type ? `: ${out.type}` : ""} = ${shortLiteral(node.props?.value, 26)}`
  }
  const w = Math.max(64, tw(text) + 30)
  const h = 28
  const ports = []
  if (out) ports.push(dataPort("out", out, w, h / 2))
  for (const p of node.ctrl_in || []) ports.push(ctrlPort("in", p, w / 2, 0))
  for (const p of node.ctrl_out || []) ports.push(ctrlPort("out", p, w / 2, h))
  return {
    w,
    h,
    shape: node.kind === "get" ? "get" : "value",
    ports,
    texts: [{ text, x: w / 2 - 3, y: h / 2 + 4, anchor: "middle", cls: "pill" }],
  }
}

// ---------------------------------------------------------------- branch: diamond

function branchGeometry(node) {
  const labels = node.props?.labels || {}
  const tText = `T \`${labels.true ?? "?"}\``
  const fText = `F \`${labels.false ?? "?"}\``
  const dw = 132
  const dh = 76
  const side = Math.max(tw(tText), tw(fText)) - dw / 4 + 18
  const pad = Math.max(0, side)
  const w = dw + 2 * pad
  const h = dh
  const cx = w / 2
  const cond = (node.inputs || [])[0] || { port: "cond" }
  const ports = [
    dataPort("in", cond, pad, h / 2),
    ...(node.ctrl_in || []).map((p) => ctrlPort("in", p, cx, 0)),
    ctrlPort("out", "true", pad + dw * 0.25, h * 0.75),
    ctrlPort("out", "false", pad + dw * 0.75, h * 0.75),
  ]
  const condText = "value" in cond ? shortLiteral(cond.value, 10) : "branch"
  return {
    w,
    h,
    shape: "diamond",
    inset: pad,
    innerW: dw,
    ports,
    texts: [
      { text: condText, x: cx, y: h / 2 + 4, anchor: "middle", cls: "title" },
      { text: tText, x: pad + dw * 0.25 - 10, y: h * 0.75 + 12, anchor: "end", cls: "ctrl" },
      { text: fText, x: pad + dw * 0.75 + 10, y: h * 0.75 + 12, anchor: "start", cls: "ctrl" },
    ],
  }
}

// ---------------------------------------------------------------- switch: hexagon

function switchGeometry(node) {
  const props = node.props || {}
  const outs = node.ctrl_out || []
  const labelOf = (port) => {
    const label = props.labels?.[port] ?? "?"
    if (port === "default") return `_ → ${label}`
    const i = Number(port.slice("case_".length))
    return `${shortLiteral(props.cases?.[i], 8)} → ${label}`
  }
  const labels = outs.map(labelOf)
  const slot = Math.max(64, ...labels.map((s) => tw(s) + 14))
  const w = Math.max(150, outs.length * slot + 32)
  const h = 58
  const value = (node.inputs || [])[0] || { port: "value" }
  const xs = spread(outs.length, 16, w - 16)
  const ports = [
    dataPort("in", value, 0, h / 2),
    ...(node.ctrl_in || []).map((p) => ctrlPort("in", p, w / 2, 0)),
    ...outs.map((p, i) => ctrlPort("out", p, xs[i], h)),
  ]
  const head = "value" in value ? `switch ${shortLiteral(value.value, 10)}` : "switch"
  return {
    w,
    h,
    shape: "hexagon",
    ports,
    texts: [
      { text: head, x: w / 2, y: 20, anchor: "middle", cls: "title" },
      ...labels.map((text, i) => ({ text, x: xs[i], y: h - 9, anchor: "middle", cls: "ctrl" })),
    ],
  }
}

// ---------------------------------------------------------------- merge: funnel

function mergeGeometry(node) {
  const ins = [...(node.ctrl_in || []), mergeSlot(node)]
  const label = node.props?.label
  const text = label ? `⟲ \`${label}\`` : "merge"
  const w = Math.max(label ? tw(text) + 44 : 64, ins.length * 26 + 16)
  const h = label ? 36 : 30
  const xs = spread(ins.length, 6, w - 6)
  const ports = [
    ...ins.map((p, i) =>
      ctrlPort("in", p, xs[i], 0, "top", i === ins.length - 1 ? { free: true } : {}),
    ),
    ...(node.ctrl_out || []).map((p) => ctrlPort("out", p, w / 2, h)),
  ]
  return {
    w,
    h,
    shape: "funnel",
    ports,
    texts: [
      { text, x: w / 2, y: h / 2 + 3, anchor: "middle", cls: label ? "loop" : "muted" },
    ],
  }
}

// ---------------------------------------------------------------- parallel: bar

function parallelGeometry(node) {
  const outs = node.ctrl_out || []
  const labels = outs.map((p) => `\`${node.props?.labels?.[p] ?? p}\``)
  const slot = Math.max(56, ...labels.map((s) => tw(s) + 16))
  const w = Math.max(120, outs.length * slot + 24)
  const h = 24
  const xs = spread(outs.length, 12, w - 12)
  return {
    w,
    h,
    shape: "bar",
    ports: [
      ...(node.ctrl_in || []).map((p) => ctrlPort("in", p, w / 2, 0)),
      ...outs.map((p, i) => ctrlPort("out", p, xs[i], h)),
    ],
    texts: labels.map((text, i) => ({ text, x: xs[i], y: h / 2 + 4, anchor: "middle", cls: "bar" })),
  }
}

/** Geometry of one node. `ctx.defNames`: names of the program's `@def` graphs. */
export function nodeGeometry(node, ctx = {}) {
  switch (node.kind) {
    case "value":
    case "get":
      return pillGeometry(node)
    case "branch":
      return branchGeometry(node)
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

/** Ports of a dataflow frame, at positions ELK chose on its border. */
export function framePorts(node, box) {
  const ports = []
  for (const p of node.ctrl_in || [])
    ports.push(ctrlPort("in", p, box.ports?.[`ctrl:in:${p}`]?.x ?? box.w / 2, 0))
  for (const p of node.ctrl_out || [])
    ports.push(ctrlPort("out", p, box.ports?.[`ctrl:out:${p}`]?.x ?? box.w / 2, box.h))
  return ports
}

/** SVG path of a node outline in its own box. */
export function shapePath(g) {
  const { w, h } = g
  switch (g.shape) {
    case "diamond": {
      const x0 = g.inset
      const x1 = g.inset + g.innerW
      const cx = w / 2
      return `M ${cx} 0 L ${x1} ${h / 2} L ${cx} ${h} L ${x0} ${h / 2} Z`
    }
    case "hexagon":
      return `M 0 ${h / 2} L 14 0 L ${w - 14} 0 L ${w} ${h / 2} L ${w - 14} ${h} L 14 ${h} Z`
    case "funnel":
      return `M 0 0 L ${w} 0 L ${w * 0.66} ${h} L ${w * 0.34} ${h} Z`
    default:
      return null
  }
}
