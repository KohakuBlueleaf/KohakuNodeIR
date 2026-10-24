/**
 * Layouts that keep elements where they are, for editing. A memory holds the
 * position of every element and the route of every wire drawn last; a kept
 * layout puts each element at its remembered position, fits each region box
 * around what it holds (the remembered box while that still holds it), and
 * routes each wire: its remembered route while both pins stay where it ends,
 * else an orthogonal one (layout/route.js). ELK runs only when some element
 * has no remembered position, and only such elements take ELK's place.
 */

import { spread } from "../geometry/port.js"
import { REGION_HEAD, REGION_PAD, regionMinWidth } from "../geometry/region.js"
import { layoutPlanned, planLayout } from "./build.js"
import { orthoRoute } from "./route.js"

const EPS = 0.5

/** `placed`: element id -> {x, y}; `boxes`: region element id -> {x, y, w, h}; `routes`: edge id -> points. */
export const createMemory = () => ({ placed: new Map(), boxes: new Map(), routes: new Map() })

export function forget(memory) {
  memory.placed.clear()
  memory.boxes.clear()
  memory.routes.clear()
}

/** Remember where `layout` put every element and wire (kept for ids that leave, so an undo finds them). */
export function remember(memory, layout) {
  for (const n of layout.nodes) memory.placed.set(n.id, { x: n.x, y: n.y })
  for (const r of layout.regions) memory.boxes.set(r.id, { x: r.x, y: r.y, w: r.w, h: r.h })
  for (const e of layout.edges) if (e.route) memory.routes.set(e.id, e.route)
}

const sideOf = (p, w, h) => (p.x <= EPS ? "left" : p.x >= w - EPS ? "right" : p.y <= EPS ? "top" : "bottom")

/** A drawn element's pin `handle` in page coordinates, with the side it sits on and the element's box. */
export function pinAt(box, handle) {
  if (!box || !handle) return null
  if (box.geom) {
    const p = box.geom.ports.find((q) => q.handle === handle)
    return p ? { x: box.x + p.x, y: box.y + p.y, side: p.side, box } : null
  }
  const p = box.ports?.[handle]
  return p ? { x: box.x + p.x, y: box.y + p.y, side: sideOf(p, box.w, box.h), box } : null
}

/** The control pins of a dataflow block's box: in on the side the flow comes from, out on the other. */
function boxPorts(box, el, direction) {
  if (!el.boxed) return {}
  const down = direction === "DOWN"
  const ports = {}
  for (const [dir, list] of [
    ["in", el.owner?.ctrl_in || []],
    ["out", el.owner?.ctrl_out || []],
  ]) {
    const at = spread(list.length, 0, down ? box.w : box.h)
    list.forEach((p, i) => {
      const edge = dir === "in" ? 0 : down ? box.h : box.w
      ports[`ctrl:${dir}:${p}`] = down ? { x: at[i], y: edge } : { x: edge, y: at[i] }
    })
  }
  return ports
}

const holds = (outer, inner) =>
  outer.x <= inner.x + EPS && outer.y <= inner.y + EPS && outer.x + outer.w >= inner.x + inner.w - EPS && outer.y + outer.h >= inner.y + inner.h - EPS

// A route ELK made may end up to a pixel off the drawn pin (ports sit on ELK's integer grid)
const PIN_SLACK = 1
const same = (p, q) => Math.abs(p.x - q.x) <= PIN_SLACK && Math.abs(p.y - q.y) <= PIN_SLACK

/**
 * The drawn layout of `plan` with every element at its remembered position
 * (else at `fallback`'s, else at the origin); the same shape `readLayout` gives.
 */
export function placeLayout(plan, memory, fallback = null) {
  const { elements, geoms, tree, drawn, direction } = plan
  const nodes = []
  const pending = []
  const kids = new Map()
  const child = (parent, box) => kids.set(parent, [...(kids.get(parent) || []), box])
  for (const [id, el] of elements) {
    const at = tree.get(id) || { parent: null, depth: 0 }
    if (el.type === "region") {
      pending.push({ id, el, ...at })
      continue
    }
    const g = geoms.get(id)
    const p = memory.placed.get(id) ?? fallback?.get(id) ?? { x: 0, y: 0 }
    const box = { id, x: p.x, y: p.y, w: g.w, h: g.h, depth: at.depth, parent: at.parent, ...(at.host ? { host: at.host } : {}), geom: g, ...el }
    nodes.push(box)
    child(at.parent, box)
  }
  // Innermost regions first, so each box fits the boxes nested in it
  pending.sort((a, b) => b.depth - a.depth)
  const regions = []
  for (const r of pending) {
    const list = kids.get(r.id) || []
    if (!list.length) continue
    const x0 = Math.min(...list.map((b) => b.x))
    const y0 = Math.min(...list.map((b) => b.y))
    const x1 = Math.max(...list.map((b) => b.x + b.w))
    const y1 = Math.max(...list.map((b) => b.y + b.h))
    const top = REGION_HEAD + 10
    const fit = { x: x0 - REGION_PAD, y: y0 - top, w: Math.max(x1 - x0 + 2 * REGION_PAD, regionMinWidth(r.el.title)), h: y1 - y0 + top + REGION_PAD }
    const kept = memory.boxes.get(r.id)
    const shape = kept && holds(kept, fit) ? kept : fit
    const box = { id: r.id, ...shape, depth: r.depth, parent: r.parent }
    const region = { ...box, ...r.el, ports: boxPorts(box, r.el, direction) }
    regions.push(region)
    child(r.parent, region)
  }
  regions.sort((a, b) => a.depth - b.depth)

  const index = new Map([...nodes, ...regions].map((b) => [b.id, b]))
  const edges = [...drawn.values()].map((e) => {
    const a = pinAt(index.get(e.source), e.sourceHandle)
    const b = pinAt(index.get(e.target), e.targetHandle)
    if (!a || !b) return { ...e, route: null, tailBox: null }
    const last = memory.routes.get(e.id)
    const route = last && same(last[0], a) && same(last[last.length - 1], b) ? last : orthoRoute(a, a.side, b, b.side, [a.box, b.box])
    return { ...e, route, tailBox: null }
  })
  const all = [...nodes, ...regions]
  const bounds = { w: Math.max(0, ...all.map((n) => n.x + n.w)), h: Math.max(0, ...all.map((n) => n.y + n.h)) }
  return Object.defineProperty({ nodes, regions, edges, bounds, direction }, "plan", { value: plan, enumerable: false })
}

/**
 * Lay out `model` in `view` keeping what `memory` remembers; `{ms, cached}`
 * time the ELK run made for elements it did not hold (0 and true when none).
 */
export async function keepLayout(model, view, opts, memory) {
  const { input, plan } = planLayout(model, view, opts)
  let fallback = null
  let ms = 0
  let cached = true
  const unplaced = [...plan.elements].some(([id, el]) => el.type !== "region" && !memory.placed.has(id))
  if (unplaced) {
    const fresh = await layoutPlanned(input, plan, opts)
    fallback = new Map(fresh.nodes.map((n) => [n.id, { x: n.x, y: n.y }]))
    ms = fresh.ms
    cached = fresh.cached
  }
  const layout = placeLayout(plan, memory, fallback)
  return Object.defineProperty({ ...layout, ms, cached }, "plan", { value: plan, enumerable: false })
}
