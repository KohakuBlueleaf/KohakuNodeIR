/**
 * One graph in one view, laid out by ELK.
 *
 * Every region is a compound node around its statements (a dataflow block's
 * compound is its owner node, which keeps its control ports); a collapsed
 * region is one box, and every edge to a node inside it ends at that box.
 * Ports sit where the geometry draws them (`FIXED_POS`), so routes end on the
 * drawn pins. Back edges (jumps back into a loop, returns into `next`) go into
 * ELK reversed, so the layering follows the flow and ELK routes them around.
 * In a view whose control only orders the layout, control edges are given to
 * ELK but not drawn, routed through the hidden join nodes.
 */

import { CTRL, typeColor } from "../model/types.js"
import { edgeKey, edgeType, isBackEdge, sourceHandle, targetHandle } from "../model/ports.js"
import { regionChain, regionNodes } from "../model/graph.js"
import { isStatement } from "../model/tree.js"
import { REGION_HEAD, REGION_PAD, collapsedGeometry, regionMinWidth, regionTitle, regionTone } from "../geometry/region.js"
import { textWidth } from "../geometry/measure.js"
import { runElk } from "./elk.js"
import { withGraphIO } from "./io.js"
import { compactLayout } from "./compact.js"
import { wrapColumns } from "./wrap.js"

const ELK_SIDE = { top: "NORTH", bottom: "SOUTH", left: "WEST", right: "EAST" }

/**
 * Above this many elements, steps ELK runs by recursion as deep as the longest
 * chain (component search, depth-first cycle breaking, network simplex
 * placement) are replaced.
 */
const SEPARATE_LIMIT = 400

const regionElement = (rid) => `region:${rid}`
const collapsedElement = (rid) => `collapsed:${rid}`

const PILLS = new Set(["get", "value", "set"])
const SATELLITE_GAP = 28
const SATELLITE_SPACE = 6

/**
 * Pills that serve exactly one port of one drawn statement, by host id: a
 * `get` or literal whose only wire feeds the host (`side: "in"`), or a `set`
 * whose only wire comes from it (`side: "out"`), one per port.
 */
function findSatellites(nodes, edges, byId, into, ownerBox, hidden) {
  const dataEdges = new Map()
  for (const e of edges) {
    if (e.kind === "ctrl") continue
    for (const id of [e.from.node, e.to.node]) dataEdges.set(id, [...(dataEdges.get(id) || []), e])
  }
  const out = new Map()
  const taken = new Set()
  for (const n of nodes) {
    if (!PILLS.has(n.kind) || into.has(n.id)) continue
    const list = dataEdges.get(n.id) || []
    if (list.length !== 1) continue
    const e = list[0]
    const side = n.kind === "set" ? "out" : "in"
    const hostId = side === "in" ? e.to.node : e.from.node
    const host = byId.get(hostId)
    if (!host || PILLS.has(host.kind) || hidden(host) || into.has(hostId) || ownerBox.has(hostId)) continue
    if ((host.region || null) !== (n.region || null)) continue
    const port = side === "in" ? e.to.port : e.from.port
    if (taken.has(`${hostId}|${side}|${port}`)) continue
    taken.add(`${hostId}|${side}|${port}`)
    out.set(hostId, [...(out.get(hostId) || []), { node: n, side, port, edge: e }])
  }
  return out
}

/**
 * The box of a statement with its satellites: pills in a column beside the
 * port each serves (pushed apart where they would touch), the statement in
 * the middle. Ports the layout sees move to the unit's border; `pins` keeps
 * where each is drawn, so a wire is extended straight from border to pin.
 */
function satelliteColumns(g, sats, geoms) {
  const columns = { in: [], out: [] }
  for (const s of sats) {
    const sg = geoms.get(s.node.id)
    const hostPort = g.ports.find((p) => p.handle === `data:${s.side}:${s.port}`)
    if (hostPort) columns[s.side].push({ ...s, sg, pin: sg.ports[0], at: hostPort })
  }
  return columns
}

const columnWidth = (list) => (list.length ? Math.max(...list.map((s) => s.sg.w)) + SATELLITE_GAP : 0)

/**
 * The pill columns shared by the units of one region whose flow runs down, so
 * pills line up beside their statements (the trunk is kept straight by the
 * control pins, not by unit widths). Null when the flow runs across.
 */
function unitFrame(hosts, direction) {
  if (direction !== "DOWN" || !hosts.length) return null
  return {
    in: Math.max(...hosts.map((h) => columnWidth(h.columns.in))),
    out: Math.max(...hosts.map((h) => columnWidth(h.columns.out))),
  }
}

/** `wired`: the handles of the host's ports that carry a wire; only those keep their rows clear of pills. */
function unitGeometry(g, columns, frame, wired) {
  const left = frame ? frame.in : columnWidth(columns.in)
  const right = frame ? frame.out : columnWidth(columns.out)
  const inEdge = left - SATELLITE_GAP
  const outEdge = left + g.w + SATELLITE_GAP
  let top = 0
  let bottom = g.h
  const servedHandles = new Set(Object.values(columns).flatMap((list) => list.map((s) => `data:${s.side}:${s.port}`)))
  for (const [dir, list] of Object.entries(columns)) {
    // The rows of the host's other ports on this side stay clear: their wires run out through the column
    const side = dir === "in" ? "left" : "right"
    const blocked = g.ports.filter((p) => p.side === side && !servedHandles.has(p.handle) && wired.has(p.handle)).map((p) => p.y)
    list.sort((a, b) => a.at.y - b.at.y)
    let floor = -Infinity
    for (const s of list) {
      s.y = Math.max(s.at.y - s.pin.y, floor)
      for (const y of [...blocked].sort((a, b) => a - b)) if (y > s.y - 4 && y < s.y + s.sg.h + 4) s.y = y + 6
      floor = s.y + s.sg.h + SATELLITE_SPACE
      top = Math.min(top, s.y)
      bottom = Math.max(bottom, s.y + s.sg.h)
    }
  }
  const ox = left
  const oy = -top
  const w = left + g.w + right
  const h = bottom - top
  const placed = [
    ...columns.in.map((s) => ({ ...s, x: inEdge - s.sg.w, y: s.y + oy })),
    ...columns.out.map((s) => ({ ...s, x: outEdge, y: s.y + oy })),
  ]
  const served = new Set(placed.map((s) => `data:${s.side}:${s.port}`))
  const ports = []
  const pins = new Map()
  for (const p of g.ports) {
    if (served.has(p.handle)) continue
    const pin = { x: p.x + ox, y: p.y + oy }
    const border = { left: { x: 0, y: pin.y }, right: { x: w, y: pin.y }, top: { x: pin.x, y: 0 }, bottom: { x: pin.x, y: h } }[p.side]
    ports.push({ ...p, ...border })
    pins.set(p.handle, pin)
  }
  return { w, h, ox, oy, ports, pins, satellites: placed }
}

/** ELK input `node` with node placement `strategy` at every level. */
function withPlacement(node, strategy) {
  if (!node.children) return node
  return {
    ...node,
    layoutOptions: { ...node.layoutOptions, "elk.layered.nodePlacement.strategy": strategy },
    children: node.children.map((c) => withPlacement(c, strategy)),
  }
}

/** An orthogonal wire between two points that leave sideways: straight, or with one step. */
function sideRoute(a, b) {
  if (Math.abs(a.y - b.y) < 0.5) return [a, b]
  const mx = (a.x + b.x) / 2
  return [a, { x: mx, y: a.y }, { x: mx, y: b.y }, b]
}

// One row of overlay marks (styles/nodes.css `.kg-marks--above`: a badge line and its gap)
const MARK_ROW = 19
const markBand = (opts) => (opts.markRows ?? 0) * MARK_ROW

/** ELK spacing; `band` is room kept over every element for its overlay marks. */
function spacing(direction, band = 0) {
  const across = direction === "RIGHT"
  return {
    "elk.spacing.nodeNode": String((across ? 28 : 30) + (across ? band : 0)),
    "elk.spacing.edgeNode": "16",
    "elk.spacing.edgeEdge": "10",
    "elk.spacing.componentComponent": "56",
    "elk.layered.spacing.nodeNodeBetweenLayers": String(across ? 64 : 40 + band),
    "elk.layered.spacing.edgeNodeBetweenLayers": "16",
    "elk.layered.spacing.edgeEdgeBetweenLayers": "10",
  }
}

/**
 * The ELK input for `model` in `view`, with the plan that turns ELK's answer
 * into drawn elements. `opts.regions === false` draws no region boxes;
 * `opts.collapsed` holds the ids of collapsed regions; `opts.direction`
 * overrides the view's; `opts.satellites === false` lays pills out as nodes
 * of their own instead of beside the port they serve; `opts.layering` and
 * `opts.placement` pick ELK's layering and node placement strategies;
 * `opts.markRows` keeps that many rows of overlay marks clear over every element;
 * `opts.editable` gives unwired inputs and literals an input box and every
 * merge a free slot to wire one more way in.
 */
export function planLayout(model, view, opts = {}) {
  const showRegions = opts.regions !== false && view.regions !== false && model.regions.size > 0
  const collapsed = new Set(showRegions ? opts.collapsed || [] : [])
  const direction = opts.direction || view.direction
  const band = markBand(opts)
  let { nodes, edges } = model.graph
  if (view.terminals) ({ nodes, edges } = withGraphIO(nodes, edges, model.name === "main"))
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const ctrlFrom = new Map()
  const backOut = new Set()
  for (const e of edges) {
    if (e.kind !== "ctrl" || !byId.has(e.from.node)) continue
    const back = isBackEdge(e, byId)
    ctrlFrom.set(`${e.to.node}|${e.to.port}`, { node: byId.get(e.from.node), port: e.from.port, back })
    if (back) backOut.add(`${e.from.node}|${e.from.port}`)
  }
  const wiredIn = new Set(edges.filter((e) => e.kind !== "ctrl").map((e) => `${e.to.node}|${e.to.port}`))
  const ctx = { defNames: model.defNames, ctrlFrom, backOut, regions: model.regions, direction, editable: !!opts.editable, wiredIn }
  const hidden = (n) => view.hideMerges && n.kind === "merge"

  // A dataflow block's box is its owner node
  const ownerBox = new Map()
  if (showRegions)
    for (const r of model.regions.values())
      if (r.kind === "dataflow" && r.owner && byId.has(r.owner.node)) ownerBox.set(r.owner.node, r.id)

  // Nodes inside a collapsed region are drawn as its box (the outermost collapsed one)
  const outermost = (rid) => {
    let found = null
    for (const id of regionChain(model, rid)) if (collapsed.has(id)) found = id
    return found
  }
  const into = new Map()
  if (collapsed.size)
    for (const n of nodes) {
      const own = ownerBox.get(n.id)
      const c = (n.region && outermost(n.region)) || (own && outermost(own))
      if (c) into.set(n.id, collapsedElement(c))
    }

  const geoms = new Map()
  // Drawn pins, and the ports ELK sees (a unit keeps the pins its satellites serve to itself)
  const pinIds = new Set()
  const portIds = new Set()
  const elements = new Map()
  const leafPorts = (id, g) =>
    g.ports.map((p) => {
      const pid = `${id}|${p.handle}`
      portIds.add(pid)
      pinIds.add(pid)
      return { id: pid, x: p.x, y: p.y, width: 0, height: 0, layoutOptions: { "elk.port.side": ELK_SIDE[p.side] } }
    })

  // A variable or literal pill serving one port of one statement is that statement's satellite
  const satellites = opts.satellites === false ? new Map() : findSatellites(nodes, edges, byId, into, ownerBox, hidden)
  const satelliteOf = new Map()
  for (const [host, list] of satellites) for (const s of list) satelliteOf.set(s.node.id, host)
  const wiredOf = new Map()
  const wire = (id, handle) => wiredOf.set(id, (wiredOf.get(id) || new Set()).add(handle))
  for (const e of edges) {
    wire(e.from.node, sourceHandle(e))
    wire(e.to.node, targetHandle(e))
  }
  const units = new Map()

  /** Elements for a list of nodes in one region: plain leaves, and units for hosts of satellites. */
  function leaves(list) {
    const hosts = []
    for (const n of list) {
      const g = view.geometry(n, ctx)
      geoms.set(n.id, g)
      elements.set(n.id, { type: "node", node: n })
      const sats = satellites.get(n.id)
      if (!sats) continue
      for (const s of sats) {
        const sg = view.geometry(s.node, ctx)
        geoms.set(s.node.id, sg)
        elements.set(s.node.id, { type: "node", node: s.node })
        for (const p of sg.ports) pinIds.add(`${s.node.id}|${p.handle}`)
      }
      hosts.push({ n, g, columns: satelliteColumns(g, sats, geoms) })
    }
    const frame = unitFrame(hosts, direction)
    const hostOf = new Map(hosts.map((h) => [h.n.id, h]))
    return list.map((n) => (hostOf.has(n.id) ? unit(n, hostOf.get(n.id), frame) : leaf(n)))
  }

  function leaf(n) {
    const g = geoms.get(n.id)
    return { id: n.id, width: g.w, height: g.h, ports: leafPorts(n.id, g), layoutOptions: { "elk.portConstraints": "FIXED_POS" } }
  }

  function unit(n, host, frame) {
    const u = unitGeometry(host.g, host.columns, frame, wiredOf.get(n.id) || new Set())
    units.set(n.id, u)
    for (const p of host.g.ports) pinIds.add(`${n.id}|${p.handle}`)
    const ports = u.ports.map((p) => {
      const pid = `${n.id}|${p.handle}`
      portIds.add(pid)
      return { id: pid, x: p.x, y: p.y, width: 0, height: 0, layoutOptions: { "elk.port.side": ELK_SIDE[p.side] } }
    })
    return { id: n.id, width: u.w, height: u.h, ports, layoutOptions: { "elk.portConstraints": "FIXED_POS" } }
  }

  function collapsedBox(rid) {
    const r = model.regions.get(rid)
    const owner = byId.get(r.owner?.node)
    const count = regionNodes(model, rid).filter((id) => isStatement(byId.get(id) || {})).length
    const g = collapsedGeometry(regionTitle(r, owner), count, direction)
    const id = collapsedElement(rid)
    geoms.set(id, g)
    elements.set(id, { type: "collapsed", region: r, owner, count })
    return { id, width: g.w, height: g.h, ports: leafPorts(id, g), layoutOptions: { "elk.portConstraints": "FIXED_POS" } }
  }

  function compound(rid) {
    const r = model.regions.get(rid)
    const owner = byId.get(r.owner?.node)
    const title = regionTitle(r, owner)
    const boxed = ownerBox.has(r.owner?.node) && ownerBox.get(r.owner.node) === rid
    const id = boxed ? owner.id : regionElement(rid)
    const ports = []
    if (boxed) {
      const [inSide, outSide] = direction === "DOWN" ? ["NORTH", "SOUTH"] : ["WEST", "EAST"]
      for (const [dir, list, side] of [
        ["in", owner.ctrl_in || [], inSide],
        ["out", owner.ctrl_out || [], outSide],
      ])
        for (const p of list) {
          const pid = `${id}|ctrl:${dir}:${p}`
          portIds.add(pid)
          pinIds.add(pid)
          ports.push({ id: pid, width: 0, height: 0, layoutOptions: { "elk.port.side": side } })
        }
    }
    elements.set(id, { type: "region", region: r, owner, title, tone: regionTone(r), boxed })
    return {
      id,
      ports,
      children: children(r.nodes, r.regions),
      layoutOptions: {
        "elk.direction": direction,
        "elk.portConstraints": "FIXED_SIDE",
        "elk.padding": `[top=${REGION_HEAD + 10},left=${REGION_PAD},bottom=${REGION_PAD},right=${REGION_PAD}]`,
        "elk.nodeSize.minimum": `(${regionMinWidth(title)}, ${REGION_HEAD + 30})`,
        "elk.nodeSize.constraints": "MINIMUM_SIZE",
        ...spacing(direction, band),
      },
    }
  }

  // A region with nothing drawn inside (an arm that only jumps) gets no box
  const filled = new Map()
  const hasContent = (rid) => {
    if (!filled.has(rid)) {
      const r = model.regions.get(rid)
      filled.set(rid, r.nodes.some((id) => byId.has(id) && !hidden(byId.get(id))) || r.regions.some(hasContent))
    }
    return filled.get(rid)
  }

  function children(nodeIds, regionIds) {
    const list = nodeIds.map((id) => byId.get(id)).filter((n) => n && !hidden(n) && !ownerBox.has(n.id) && !satelliteOf.has(n.id))
    const out = leaves(list)
    for (const rid of regionIds) if (hasContent(rid)) out.push(collapsed.has(rid) ? collapsedBox(rid) : compound(rid))
    return out
  }

  const top = showRegions
    ? children(
        nodes.filter((n) => !n.region).map((n) => n.id),
        model.roots,
      )
    : leaves(nodes.filter((n) => !hidden(n) && !satelliteOf.has(n.id)))

  // ---------------------------------------------------------------- edges
  function end(nodeId, handle) {
    const box = into.get(nodeId)
    if (box) {
      const [flow, dir] = handle.split(":")
      const h = `${flow}:${dir}:*`
      return { el: box, handle: h, port: `${box}|${h}` }
    }
    const pid = `${nodeId}|${handle}`
    return { el: nodeId, handle: pinIds.has(pid) ? handle : null, port: portIds.has(pid) ? pid : null }
  }

  const drawn = new Map()
  const layoutOnly = []
  const elkEdges = []
  const reversed = new Set()

  // Control that only orders the layout skips back edges and runs through hidden joins
  const ctrlOut = new Map()
  for (const e of edges) if (e.kind === "ctrl") ctrlOut.set(e.from.node, [...(ctrlOut.get(e.from.node) || []), e])
  const through = (nodeId, seen = new Set()) => {
    const n = byId.get(nodeId)
    if (!n || !hidden(n)) return [nodeId]
    if (seen.has(nodeId)) return []
    seen.add(nodeId)
    return (ctrlOut.get(nodeId) || []).filter((e) => !isBackEdge(e, byId)).flatMap((e) => through(e.to.node, seen))
  }

  for (const e of edges) {
    if (e.kind === "ctrl" && view.ctrl === "none") continue
    if (e.kind === "ctrl" && view.ctrl === "layout") {
      const src = byId.get(e.from.node)
      if (!src || hidden(src) || isBackEdge(e, byId)) continue
      for (const t of through(e.to.node)) {
        const a = into.get(e.from.node) || e.from.node
        const b = into.get(t) || t
        if (a !== b && elements.has(a) && elements.has(b)) layoutOnly.push([a, b])
      }
      continue
    }
    if (!byId.has(e.from.node) || !byId.has(e.to.node)) continue
    const s = end(e.from.node, sourceHandle(e))
    const t = end(e.to.node, targetHandle(e))
    if (s.el === t.el && into.has(e.from.node)) continue
    const id = into.has(e.from.node) || into.has(e.to.node) ? `${e.kind}|${s.el}|${s.handle}|${t.el}|${t.handle}` : edgeKey(e)
    const seen = drawn.get(id)
    if (seen) {
      seen.keys.push(edgeKey(e))
      continue
    }
    const back = isBackEdge(e, byId)
    const robo = view.palette === "robo"
    const color =
      e.kind === "ctrl" ? (robo ? "var(--kg-robo-flow)" : CTRL) : robo ? "var(--kg-robo-data)" : typeColor(edgeType(e, byId))
    const tail = view.tailLabel?.(byId.get(e.from.node), e.from.port) ?? null
    drawn.set(id, {
      id,
      kind: e.kind,
      back,
      color,
      arrow: !!view.arrows && e.kind === "ctrl",
      tail,
      source: s.el,
      target: t.el,
      sourceHandle: s.handle,
      targetHandle: t.handle,
      keys: [edgeKey(e)],
    })
    // A satellite's wire is drawn from the unit's own placement, not routed by ELK
    if (satelliteOf.has(e.from.node) || satelliteOf.has(e.to.node)) continue
    const ends = [s.port || s.el, t.port || t.el]
    if (back) {
      ends.reverse()
      reversed.add(id)
    }
    const elkEdge = { id, sources: [ends[0]], targets: [ends[1]] }
    // The trunk (control running forward) is kept straight and short before anything else; data yields
    elkEdge.layoutOptions =
      e.kind === "ctrl" && !back
        ? { "elk.layered.priority.straightness": "100", "elk.layered.priority.shortness": "100" }
        : { "elk.layered.priority.straightness": "0", "elk.layered.priority.shortness": "0" }
    // The label sits where the wire leaves its source: ELK's tail, or its head when reversed
    if (tail)
      elkEdge.labels = [
        {
          id: `${id}|tail`,
          text: tail,
          width: textWidth(tail, "small") + 8,
          height: 14,
          layoutOptions: { "elk.edgeLabels.placement": back ? "HEAD" : "TAIL" },
        },
      ]
    elkEdges.push(elkEdge)
  }
  layoutOnly.forEach(([a, b], i) => elkEdges.push({ id: `layout|${i}`, sources: [a], targets: [b] }))

  const input = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": direction,
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.json.edgeCoords": "ROOT",
      "elk.layered.cycleBreaking.strategy": geoms.size <= SEPARATE_LIMIT ? "DEPTH_FIRST" : "GREEDY",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.nodePlacement.strategy": opts.placement ?? (geoms.size <= SEPARATE_LIMIT ? "NETWORK_SIMPLEX" : "BRANDES_KOEPF"),
      ...(opts.layering ? { "elk.layered.layering.strategy": opts.layering } : {}),
      "elk.layered.nodePlacement.favorStraightEdges": "true",
      // ELK finds components by recursion as deep as the longest chain
      "elk.separateConnectedComponents": String(geoms.size <= SEPARATE_LIMIT),
      ...spacing(direction, band),
    },
    children: top,
    edges: elkEdges,
  }
  // Where each element sits in the region tree: its enclosing element and depth (satellites beside their host)
  const tree = new Map()
  const walk = (elkNode, parent, depth) => {
    for (const c of elkNode.children || []) {
      tree.set(c.id, { parent, depth })
      for (const s of units.get(c.id)?.satellites || []) tree.set(s.node.id, { parent, depth, host: c.id })
      walk(c, c.id, depth + 1)
    }
  }
  walk(input, null, 0)
  return { input, plan: { model, view, direction, geoms, elements, drawn, reversed, units, tree } }
}

/** The drawn layout from ELK's answer: nodes, region boxes and edges with routes, in page coordinates. */
export function readLayout(result, plan) {
  const nodes = []
  const regions = []
  const units = new Map()
  const walk =(elkNode, ox, oy, depth, parent) => {
    for (const c of elkNode.children || []) {
      const x = ox + c.x
      const y = oy + c.y
      const el = plan.elements.get(c.id)
      if (!el) continue
      const box = { id: c.id, x, y, w: c.width, h: c.height, depth, parent }
      const unit = plan.units.get(c.id)
      if (el.type === "region") {
        const ports = {}
        for (const p of c.ports || []) ports[p.id.slice(c.id.length + 1)] = { x: p.x, y: p.y }
        regions.push({ ...box, ...el, ports })
        walk(c, x, y, depth + 1, c.id)
      } else if (unit) {
        const g = plan.geoms.get(c.id)
        nodes.push({ ...box, x: x + unit.ox, y: y + unit.oy, w: g.w, h: g.h, geom: g, ...el })
        for (const s of unit.satellites)
          nodes.push({ id: s.node.id, x: x + s.x, y: y + s.y, w: s.sg.w, h: s.sg.h, depth, parent, host: c.id, geom: s.sg, ...plan.elements.get(s.node.id) })
        units.set(c.id, { x, y, unit })
      } else nodes.push({ ...box, geom: plan.geoms.get(c.id), ...el })
    }
  }
  walk(result, 0, 0, 0, null)

  const routes = new Map()
  const labels = new Map()
  const collect = (elkNode) => {
    for (const e of elkNode.edges || []) {
      const s = e.sections?.[0]
      if (s) routes.set(e.id, [s.startPoint, ...(s.bendPoints || []), s.endPoint].map((p) => ({ x: p.x, y: p.y })))
      const l = e.labels?.[0]
      if (l) labels.set(e.id, { x: l.x, y: l.y, w: l.width, h: l.height })
    }
    for (const c of elkNode.children || []) collect(c)
  }
  collect(result)
  // Satellite wires run beside their unit; other wires at a unit run on from its border to the pin
  const satWires = new Map()
  for (const { x, y, unit } of units.values())
    for (const s of unit.satellites) {
      const pill = { x: x + s.x + s.pin.x, y: y + s.y + s.pin.y }
      const host = { x: x + unit.ox + s.at.x, y: y + unit.oy + s.at.y }
      satWires.set(edgeKey(s.edge), s.side === "in" ? sideRoute(pill, host) : sideRoute(host, pill))
    }
  const pinOf = (el, handle) => {
    const u = units.get(el)
    const p = u && handle && u.unit.pins.get(handle)
    return p ? { x: u.x + p.x, y: u.y + p.y } : null
  }
  const edges = [...plan.drawn.values()].map((e) => {
    let route = satWires.get(e.id) || routes.get(e.id) || null
    if (route && plan.reversed.has(e.id)) route.reverse()
    if (route && !satWires.has(e.id)) {
      const a = pinOf(e.source, e.sourceHandle)
      const b = pinOf(e.target, e.targetHandle)
      route = [...(a ? [a] : []), ...route, ...(b ? [b] : [])]
    }
    return { ...e, route, tailBox: labels.get(e.id) || null }
  })
  const all = [...nodes, ...regions]
  const bounds = {
    w: Math.max(0, ...all.map((n) => n.x + n.w)),
    h: Math.max(0, ...all.map((n) => n.y + n.h)),
  }
  return { nodes, regions, edges, bounds, direction: plan.direction }
}

/**
 * Lay out `model` in `view`; the drawn layout plus `{ms, cached}` timing. A
 * flow running down is compacted up and left (layout/compact.js; `opts.compact`,
 * on up to SEPARATE_LIMIT elements by default), cut into macro columns near
 * aspect ratio `opts.aspect` (1.4) unless `opts.wrap === false`
 * (layout/wrap.js), and compacted again once cut.
 */
export async function layoutView(model, view, opts = {}) {
  const { input, plan } = planLayout(model, view, opts)
  return layoutPlanned(input, plan, opts)
}

/** `layoutView` of a plan already made; the result carries the plan. */
export async function layoutPlanned(input, plan, opts = {}) {
  let run
  try {
    run = await runElk(input)
  } catch {
    // ELK's network simplex placement fails on some nested graphs; Brandes-Köpf places every one
    run = await runElk(withPlacement(input, "BRANDES_KOEPF"))
  }
  const { result, ms, cached } = run
  let layout = readLayout(result, plan)
  if (layout.direction === "DOWN") {
    const compact = opts.compact ?? plan.geoms.size <= SEPARATE_LIMIT
    const band = markBand(opts)
    if (compact) layout = compactLayout(layout, { band })
    if (opts.wrap !== false) layout = wrapColumns(layout, opts.aspect ?? 1.4)
    if (compact && layout.columns) layout = compactLayout(layout, { band })
  }
  // The plan rides along unlisted, so a layout still prints and compares as plain data
  return Object.defineProperty({ ...layout, ms, cached }, "plan", { value: plan, enumerable: false })
}
