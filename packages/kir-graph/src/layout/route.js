/**
 * Orthogonal wires between two pins whose elements were placed by hand (or
 * kept in place across an edit), where ELK has no route: out of the source
 * pin and into the target pin along the sides they sit on, with one bend
 * between when both run the same axis, and around both elements when the
 * target lies behind the source.
 */

const STUB = 16
const LANE = 20
const EPS = 0.5

const OUT = { top: { x: 0, y: -1 }, bottom: { x: 0, y: 1 }, left: { x: -1, y: 0 }, right: { x: 1, y: 0 } }

/** A route without repeated points or points in the middle of a straight run. */
export function cleanRoute(points) {
  const out = []
  for (const p of points) {
    const last = out[out.length - 1]
    if (last && Math.abs(last.x - p.x) < EPS && Math.abs(last.y - p.y) < EPS) continue
    out.push({ x: p.x, y: p.y })
  }
  for (let i = out.length - 2; i > 0; i--) {
    const [a, b, c] = [out[i - 1], out[i], out[i + 1]]
    const vertical = Math.abs(a.x - b.x) < EPS && Math.abs(b.x - c.x) < EPS
    const horizontal = Math.abs(a.y - b.y) < EPS && Math.abs(b.y - c.y) < EPS
    if (vertical || horizontal) out.splice(i, 1)
  }
  return out
}

/** The lane past every box on one side of an axis, on the side nearer the two ends. */
function lane(boxes, a, b, axis) {
  const lo = Math.min(...boxes.map((r) => r[axis])) - LANE
  const hi = Math.max(...boxes.map((r) => r[axis] + (axis === "x" ? r.w : r.h))) + LANE
  return Math.abs(a[axis] - lo) + Math.abs(b[axis] - lo) < Math.abs(a[axis] - hi) + Math.abs(b[axis] - hi) ? lo : hi
}

/**
 * The route from pin `a` (on side `sa` of its element) to pin `b` (on side
 * `sb`). `boxes` are the two elements `{x, y, w, h}`, which a wire running
 * back goes around.
 */
export function orthoRoute(a, sa, b, sb, boxes = []) {
  const da = OUT[sa] || OUT.right
  const db = OUT[sb] || OUT.left
  const a1 = { x: a.x + da.x * STUB, y: a.y + da.y * STUB }
  const b1 = { x: b.x + db.x * STUB, y: b.y + db.y * STUB }
  const around = boxes.length ? boxes : [{ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) }]
  let mid
  // Facing ends with the target ahead step once, halfway between the pins
  if (da.y && db.y && da.y === -db.y && (b.y - a.y) * da.y > 0) {
    const y = (a.y + b.y) / 2
    return cleanRoute([a, { x: a.x, y }, { x: b.x, y }, b])
  }
  if (da.x && db.x && da.x === -db.x && (b.x - a.x) * da.x > 0) {
    const x = (a.x + b.x) / 2
    return cleanRoute([a, { x, y: a.y }, { x, y: b.y }, b])
  }
  if (da.y && db.y) {
    if (da.y === db.y) {
      const y = da.y > 0 ? Math.max(a1.y, b1.y) : Math.min(a1.y, b1.y)
      mid = [{ x: a1.x, y }, { x: b1.x, y }]
    } else {
      const x = lane(around, a, b, "x")
      mid = [{ x, y: a1.y }, { x, y: b1.y }]
    }
  } else if (da.x && db.x) {
    if (da.x === db.x) {
      const x = da.x > 0 ? Math.max(a1.x, b1.x) : Math.min(a1.x, b1.x)
      mid = [{ x, y: a1.y }, { x, y: b1.y }]
    } else {
      const y = lane(around, a, b, "y")
      mid = [{ x: a1.x, y }, { x: b1.x, y }]
    }
  } else if (da.y) mid = [{ x: b1.x, y: a1.y }]
  else mid = [{ x: a1.x, y: b1.y }]
  return cleanRoute([a, a1, ...mid, b1, b])
}
