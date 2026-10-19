/**
 * ELK layered layout of one graph, top to bottom along control flow.
 *
 * Every port is given to ELK at its fixed position and side (control
 * NORTH/SOUTH, data WEST/EAST), so routes end where the handles are drawn.
 * Back edges (jumps back into a labelled merge, returns into an `each` node's
 * `next` port) go into ELK reversed, so the layering follows control flow and
 * ELK routes them around the loop body. A dataflow node becomes a compound
 * node holding its members.
 */

import ElkApi from "elkjs/lib/elk-api.js"
import elkWorkerUrl from "elkjs/lib/elk-worker.min.js?url"

import { handleId, nodeGeometry } from "@/graph/geometry"

const ELK_SIDE = { top: "NORTH", bottom: "SOUTH", left: "WEST", right: "EAST" }
export const FRAME_PAD = { top: 34, side: 18, bottom: 18 }

const WORKER_TIMEOUT_MS = 5000

let workerElk = null
let mainElk = null

/**
 * Run ELK in a web worker; when the worker cannot run or does not answer in
 * time (some embedded and headless browsers), run it on the main thread.
 */
async function runElk(graph) {
  if (!mainElk && typeof Worker !== "undefined") {
    workerElk ||= new ElkApi({ workerUrl: elkWorkerUrl })
    let timer
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("worker timeout")), WORKER_TIMEOUT_MS)
    })
    try {
      return await Promise.race([workerElk.layout(structuredClone(graph)), timeout])
    } catch (e) {
      if (!String(e?.message || e).includes("worker")) throw e
      workerElk.terminateWorker?.()
      workerElk = null
    } finally {
      clearTimeout(timer)
    }
  }
  if (!mainElk) {
    const { default: ElkBundled } = await import("elkjs/lib/elk.bundled.js")
    mainElk = new ElkBundled()
  }
  return mainElk.layout(graph)
}

export const edgeKey = (e) =>
  `${e.kind}|${e.from.node}|${e.from.port}|${e.to.node}|${e.to.port}`

export const sourceHandle = (e) => handleId(e.kind === "ctrl" ? "ctrl" : "data", "out", e.from.port)
export const targetHandle = (e) => handleId(e.kind === "ctrl" ? "ctrl" : "data", "in", e.to.port)

/** A control edge closing a loop: into a labelled merge (a jump back), or into an `each` node's `next`. */
export function isBackEdge(e, byId) {
  if (e.kind !== "ctrl") return false
  const target = byId.get(e.to.node)
  if (target?.kind === "each") return e.to.port === "next"
  if (target?.kind !== "merge" || !target.props?.label) return false
  // The first entry into a loop merge comes from before the loop; the others come back to it.
  return e.to.port !== "in_0"
}

/** Map member node id -> dataflow node id. */
export function membership(graph) {
  const out = new Map()
  for (const n of graph.nodes)
    if (n.kind === "dataflow") for (const m of n.props?.members || []) out.set(m, n.id)
  return out
}

function borderPoint(p, w, h) {
  if (p.side === "top") return { x: p.x, y: 0 }
  if (p.side === "bottom") return { x: p.x, y: h }
  if (p.side === "left") return { x: 0, y: p.y }
  return { x: w, y: p.y }
}

function leaf(node, ctx, portIds) {
  const g = nodeGeometry(node, ctx)
  const ports = g.ports.map((p) => {
    const id = `${node.id}|${p.handle}`
    portIds.add(id)
    return {
      id,
      ...borderPoint(p, g.w, g.h),
      width: 0,
      height: 0,
      layoutOptions: { "elk.port.side": ELK_SIDE[p.side] },
    }
  })
  return {
    id: node.id,
    width: g.w,
    height: g.h,
    ports,
    layoutOptions: { "elk.portConstraints": "FIXED_POS" },
  }
}

function frame(node, members, portIds) {
  const ports = [
    ...(node.ctrl_in || []).map((p) => [handleId("ctrl", "in", p), "NORTH"]),
    ...(node.ctrl_out || []).map((p) => [handleId("ctrl", "out", p), "SOUTH"]),
  ].map(([h, side]) => {
    const id = `${node.id}|${h}`
    portIds.add(id)
    return { id, width: 0, height: 0, layoutOptions: { "elk.port.side": side } }
  })
  return {
    id: node.id,
    ports,
    children: members,
    layoutOptions: {
      "elk.portConstraints": "FIXED_SIDE",
      "elk.padding": `[top=${FRAME_PAD.top},left=${FRAME_PAD.side},bottom=${FRAME_PAD.bottom},right=${FRAME_PAD.side}]`,
      "elk.nodeSize.minimum": "(160, 60)",
      "elk.nodeSize.constraints": "MINIMUM_SIZE",
    },
  }
}

export function buildElkGraph(graph, ctx) {
  const memberOf = membership(graph)
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const portIds = new Set()
  const children = []
  for (const n of graph.nodes) {
    if (memberOf.has(n.id)) continue
    if (n.kind === "dataflow") {
      const members = (n.props?.members || [])
        .map((m) => byId.get(m))
        .filter(Boolean)
        .map((m) => leaf(m, ctx, portIds))
      children.push(frame(n, members, portIds))
    } else {
      children.push(leaf(n, ctx, portIds))
    }
  }
  const edges = []
  const reversed = new Set()
  for (const e of graph.edges) {
    if (!byId.has(e.from.node) || !byId.has(e.to.node)) continue
    const s = `${e.from.node}|${sourceHandle(e)}`
    const t = `${e.to.node}|${targetHandle(e)}`
    const ends = [portIds.has(s) ? s : e.from.node, portIds.has(t) ? t : e.to.node]
    // A back edge goes into ELK reversed, so the graph it layers is acyclic.
    if (isBackEdge(e, byId)) {
      ends.reverse()
      reversed.add(edgeKey(e))
    }
    edges.push({ id: edgeKey(e), sources: [ends[0]], targets: [ends[1]] })
  }
  return {
    id: "root",
    reversed,
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.json.edgeCoords": "ROOT",
      "elk.spacing.nodeNode": "36",
      "elk.spacing.edgeNode": "16",
      "elk.spacing.edgeEdge": "10",
      "elk.spacing.componentComponent": "60",
      "elk.layered.spacing.nodeNodeBetweenLayers": "44",
      "elk.layered.spacing.edgeNodeBetweenLayers": "16",
      "elk.layered.spacing.edgeEdgeBetweenLayers": "10",
      "elk.layered.cycleBreaking.strategy": "DEPTH_FIRST",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.layered.nodePlacement.favorStraightEdges": "true",
      "elk.separateConnectedComponents": "true",
    },
    children,
    edges,
  }
}

function collectRoutes(node, out) {
  for (const e of node.edges || []) {
    const s = e.sections?.[0]
    if (!s) continue
    out[e.id] = [s.startPoint, ...(s.bendPoints || []), s.endPoint].map((p) => ({ x: p.x, y: p.y }))
  }
  for (const c of node.children || []) collectRoutes(c, out)
}

/**
 * Lay out one graph. Resolves to
 * `{positions: {id: {x, y}}, frames: {id: {w, h, ports: {handle: {x, y}}}}, routes: {edgeKey: [{x, y}]}, absolute: {id: {x, y}}}`;
 * member positions are relative to their frame, `absolute` holds page positions.
 */
export async function layoutGraph(graph, ctx) {
  const { reversed, ...input } = buildElkGraph(graph, ctx)
  const result = await runElk(input)
  const positions = {}
  const absolute = {}
  const frames = {}
  for (const c of result.children || []) {
    positions[c.id] = { x: c.x, y: c.y }
    absolute[c.id] = { x: c.x, y: c.y }
    if (c.children) {
      const ports = {}
      for (const p of c.ports || []) ports[p.id.slice(c.id.length + 1)] = { x: p.x, y: p.y }
      frames[c.id] = { w: c.width, h: c.height, ports }
      for (const m of c.children) {
        positions[m.id] = { x: m.x, y: m.y }
        absolute[m.id] = { x: c.x + m.x, y: c.y + m.y }
      }
    }
  }
  const routes = {}
  collectRoutes(result, routes)
  for (const key of reversed) routes[key]?.reverse()
  return { positions, absolute, frames, routes }
}
