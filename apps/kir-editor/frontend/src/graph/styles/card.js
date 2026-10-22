/**
 * Node-view geometry (ComfyUI / Blender / Unreal family): data flows left to
 * right, every port sits on a side. A node is a card: a header with its
 * title, then rows; each row has at most one port on the left (an input)
 * and one on the right (an output). Unwired data inputs carry an input box
 * (widget) in their row. Control ("exec") pins sit in the header when the
 * node has a single way in and out, else in rows of their own.
 *
 * Variables and literals are compact pills: `get x` (output right), `set x`
 * (input left), and a literal (output right).
 */

import { handleId, mergeSlot } from "@/graph/ports"
import { shortLiteral } from "@/graph/literal"
import { CTRL_COLOR, typeColor } from "@/graph/types"

export const HEAD = 30
export const ROW = 26
const PAD = 8
const CHAR = 6.6
const WIDGET = 96
const PILL_H = 28

const tw = (s) => Math.ceil(String(s).length * CHAR)

function ctrlLabel(node, dir, name) {
  const p = node.props || {}
  if (dir === "in") return name === "next" ? "next ⟲" : name.startsWith("in_") ? "" : name
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

const TITLE = {
  assign: () => "assign",
  branch: () => "branch",
  switch: () => "switch",
  merge: (n) => (n.props?.label ? `loop ${n.props.label}` : "merge"),
  each: () => "each",
  collect: () => "collect · capture at body end",
  parallel: () => "parallel",
  try: (n) => (n.props?.error_name ? `try · except ${n.props.error_name}` : "try"),
  inputs: () => "inputs",
  outputs: () => "outputs",
}

/** Accent family per kind: the header colour of a card. */
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
  inputs: "sage",
  outputs: "sage",
}

function pill(node) {
  let text
  let ports
  if (node.kind === "value") {
    text = shortLiteral(node.props?.value, 24)
    const w = Math.max(64, tw(text) + 42)
    ports = [port("data", "out", (node.outputs || [])[0] || { port: "value" }, w, PILL_H / 2)]
    return { w, h: PILL_H, shape: "pill", variant: "value", title: text, ports, rows: [] }
  }
  text = node.props?.name ?? "?"
  const w = Math.max(58, tw(text) + 40)
  ports =
    node.kind === "get"
      ? [port("data", "out", (node.outputs || [])[0] || { port: "value" }, w, PILL_H / 2)]
      : [port("data", "in", (node.inputs || [])[0] || { port: "value" }, 0, PILL_H / 2)]
  return { w, h: PILL_H, shape: "pill", variant: node.kind, title: text, ports, rows: [] }
}

function port(flow, dir, p, x, y, extra = {}) {
  const name = typeof p === "string" ? p : p.port
  return {
    handle: handleId(flow, dir, name),
    name,
    flow,
    dir,
    side: dir === "in" ? "left" : "right",
    x,
    y,
    type: flow === "data" ? p.type || null : null,
    color: flow === "data" ? typeColor(p.type) : CTRL_COLOR,
    ...extra,
  }
}

/**
 * Geometry of one node. `ctx.defNames`: names of the program's `@def`
 * graphs; `ctx.exec === false` leaves control pins out (control drawn as
 * frames, or not at all).
 */
export function cardGeometry(node, ctx = {}) {
  if (node.kind === "value" || node.kind === "get" || node.kind === "set") return pill(node)
  const exec = ctx.exec !== false
  const ctrlIn = exec ? [...(node.ctrl_in || [])] : []
  if (exec && node.kind === "merge") ctrlIn.push(mergeSlot(node))
  const ctrlOut = exec ? node.ctrl_out || [] : []
  const headIn = ctrlIn.includes("in") ? "in" : null
  const headOut = ctrlOut.length === 1 ? ctrlOut[0] : null
  const left = [
    ...ctrlIn.filter((c) => c !== headIn).map((c) => ({ flow: "ctrl", name: c, label: ctrlLabel(node, "in", c), free: c === mergeSlot(node) && node.kind === "merge" })),
    ...(node.inputs || []).map((p) => ({ flow: "data", p, label: p.deferred === "body_end" ? `${p.port} (body end)` : p.port })),
  ]
  const right = [
    ...ctrlOut.filter((c) => c !== headOut).map((c) => ({ flow: "ctrl", name: c, label: ctrlLabel(node, "out", c) })),
    ...(node.outputs || []).map((p) => ({
      flow: "data",
      p,
      label: p.var && p.var !== p.port ? `${p.port} → ${p.var}` : p.port,
    })),
  ]
  const isDef = node.kind === "call" && ctx.defNames?.has(node.name)
  const title = node.kind === "call" ? node.name : (TITLE[node.kind] || (() => node.kind))(node)
  const rows = Math.max(left.length, right.length)
  const leftW = Math.max(0, ...left.map((r) => tw(r.label) + (r.flow === "data" ? WIDGET + 8 : 0)))
  const rightW = Math.max(0, ...right.map((r) => tw(r.label)))
  const w = Math.max(168, tw(title) + 64, leftW + rightW + 40)
  const h = HEAD + rows * ROW + PAD

  const ports = []
  const rowList = []
  if (headIn) ports.push(port("ctrl", "in", "in", 0, HEAD / 2, { header: true }))
  if (headOut) ports.push(port("ctrl", "out", headOut, w, HEAD / 2, { header: true }))
  for (let i = 0; i < rows; i++) {
    const y = HEAD + i * ROW + ROW / 2
    const row = { y }
    const l = left[i]
    const r = right[i]
    if (l) {
      const pt =
        l.flow === "ctrl"
          ? port("ctrl", "in", l.name, 0, y, { free: l.free })
          : port("data", "in", l.p, 0, y, { input: l.p })
      ports.push(pt)
      row.left = { ...pt, label: l.label }
    }
    if (r) {
      const pt = r.flow === "ctrl" ? port("ctrl", "out", r.name, w, y) : port("data", "out", r.p, w, y)
      ports.push(pt)
      row.right = { ...pt, label: r.label }
    }
    rowList.push(row)
  }
  return {
    w,
    h,
    shape: "card",
    variant: isDef ? "defcall" : node.kind,
    accent: ACCENT[isDef ? "defcall" : node.kind] || "sapphire",
    title,
    ports,
    rows: rowList,
  }
}
