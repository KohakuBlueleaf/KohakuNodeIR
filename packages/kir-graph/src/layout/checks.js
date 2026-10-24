/**
 * Geometry properties of a drawn layout, each a list of violations (empty when
 * it holds):
 * - `overlaps`: two node boxes that intersect;
 * - `escapes`: a node or region box not inside the region box holding it;
 * - `regionOverlaps`: two region boxes under the same parent that intersect;
 * - `unrouted`: a drawn edge without a route;
 * - `detached`: a route whose end is not on the pin it connects (beyond `tol` px);
 * - `oblique`: a route with a segment neither horizontal nor vertical.
 */

const EPS = 0.5

const intersects = (a, b) =>
  a.x < b.x + b.w - EPS && b.x < a.x + a.w - EPS && a.y < b.y + b.h - EPS && b.y < a.y + a.h - EPS

const inside = (a, b) =>
  a.x >= b.x - EPS && a.y >= b.y - EPS && a.x + a.w <= b.x + b.w + EPS && a.y + a.h <= b.y + b.h + EPS

/** Pairs of intersecting boxes, by a sweep over x. */
function intersecting(boxes) {
  const sorted = [...boxes].sort((a, b) => a.x - b.x)
  const out = []
  for (let i = 0; i < sorted.length; i++) {
    const a = sorted[i]
    for (let j = i + 1; j < sorted.length && sorted[j].x < a.x + a.w - EPS; j++)
      if (intersects(a, sorted[j])) out.push([a.id, sorted[j].id])
  }
  return out
}

/** The page position of the pin `handle` of element `el` in `layout`, or null. */
export function pinAt(layout, elId, handle) {
  if (!handle) return null
  const node = layout.nodes.find((n) => n.id === elId)
  if (node) {
    const p = node.geom?.ports?.find((q) => q.handle === handle)
    return p ? { x: node.x + p.x, y: node.y + p.y } : null
  }
  const region = layout.regions.find((r) => r.id === elId)
  const p = region?.ports?.[handle]
  return p ? { x: region.x + p.x, y: region.y + p.y } : null
}

export function checkLayout(layout, tol = 1.5) {
  const boxes = new Map([...layout.nodes, ...layout.regions].map((b) => [b.id, b]))
  const escapes = []
  for (const b of boxes.values()) {
    const parent = b.parent && boxes.get(b.parent)
    if (parent && !inside(b, parent)) escapes.push(b.id)
  }
  const byParent = new Map()
  for (const r of layout.regions) byParent.set(r.parent, [...(byParent.get(r.parent) || []), r])
  const regionOverlaps = [...byParent.values()].flatMap(intersecting)

  const unrouted = []
  const detached = []
  const oblique = []
  for (const e of layout.edges) {
    if (!e.route || e.route.length < 2) {
      unrouted.push(e.id)
      continue
    }
    if (e.route.some((p, i) => i > 0 && Math.abs(p.x - e.route[i - 1].x) > EPS && Math.abs(p.y - e.route[i - 1].y) > EPS)) oblique.push(e.id)
    const ends = [
      [pinAt(layout, e.source, e.sourceHandle), e.route[0]],
      [pinAt(layout, e.target, e.targetHandle), e.route[e.route.length - 1]],
    ]
    for (const [pin, point] of ends)
      if (pin && Math.hypot(pin.x - point.x, pin.y - point.y) > tol) {
        detached.push(e.id)
        break
      }
  }
  return { overlaps: intersecting(layout.nodes), escapes, regionOverlaps, unrouted, detached, oblique }
}

export const layoutOk = (c) => Object.values(c).every((list) => list.length === 0)
