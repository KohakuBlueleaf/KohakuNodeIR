/** SVG paths for wires. */

/** An orthogonal polyline with rounded corners. */
export function roundedPath(points, radius = 6) {
  const pts = points.filter(
    (p, i) => i === 0 || Math.abs(p.x - points[i - 1].x) > 0.5 || Math.abs(p.y - points[i - 1].y) > 0.5,
  )
  if (pts.length < 2) return ""
  let d = `M ${pts[0].x} ${pts[0].y}`
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i - 1]
    const b = pts[i]
    const c = pts[i + 1]
    const r = Math.min(radius, dist(a, b) / 2, dist(b, c) / 2)
    const p1 = toward(b, a, r)
    const p2 = toward(b, c, r)
    d += ` L ${p1.x} ${p1.y} Q ${b.x} ${b.y} ${p2.x} ${p2.y}`
  }
  const last = pts[pts.length - 1]
  return `${d} L ${last.x} ${last.y}`
}

const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y)

function toward(from, to, r) {
  const d = dist(from, to) || 1
  return { x: from.x + ((to.x - from.x) * r) / d, y: from.y + ((to.y - from.y) * r) / d }
}

/**
 * A control edge that returns leftwards into a left-side port (node view):
 * out to the right of the source, under both ends, back in from the left.
 */
export function loopPointsLeft(sx, sy, tx, ty, lane = 40) {
  const y = Math.max(sy, ty) + lane
  return [
    { x: sx, y: sy },
    { x: sx + 16, y: sy },
    { x: sx + 16, y },
    { x: tx - 16, y },
    { x: tx - 16, y: ty },
    { x: tx, y: ty },
  ]
}

/**
 * A control edge that returns upwards (into a loop entry, or an `each` node's
 * `next` port on its right side): out below the source, round the right of
 * both ends, back in from above or from the right.
 */
export function loopPoints(sx, sy, tx, ty, intoRight, lane = 48) {
  const x = Math.max(sx, tx) + lane
  const down = { x: sx, y: sy + 16 }
  if (intoRight) return [{ x: sx, y: sy }, down, { x, y: down.y }, { x, y: ty }, { x: tx, y: ty }]
  const up = ty - 16
  return [
    { x: sx, y: sy },
    down,
    { x, y: down.y },
    { x, y: up },
    { x: tx, y: up },
    { x: tx, y: ty },
  ]
}
