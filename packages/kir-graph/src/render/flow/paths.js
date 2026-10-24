/** SVG paths of routed wires. */

const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y)

function toward(from, to, r) {
  const d = dist(from, to) || 1
  return { x: from.x + ((to.x - from.x) * r) / d, y: from.y + ((to.y - from.y) * r) / d }
}

/** An orthogonal polyline with its corners rounded by `radius`. */
export function roundedPath(points, radius = 6) {
  const pts = points.filter((p, i) => i === 0 || dist(p, points[i - 1]) > 0.5)
  if (pts.length < 2) return ""
  let d = `M ${pts[0].x} ${pts[0].y}`
  for (let i = 1; i < pts.length - 1; i++) {
    const [a, b, c] = [pts[i - 1], pts[i], pts[i + 1]]
    const r = Math.min(radius, dist(a, b) / 2, dist(b, c) / 2)
    const p1 = toward(b, a, r)
    const p2 = toward(b, c, r)
    d += ` L ${p1.x} ${p1.y} Q ${b.x} ${b.y} ${p2.x} ${p2.y}`
  }
  const last = pts[pts.length - 1]
  return `${d} L ${last.x} ${last.y}`
}

/** The point halfway along a polyline. */
export function midpoint(points) {
  let total = 0
  for (let i = 1; i < points.length; i++) total += dist(points[i - 1], points[i])
  let left = total / 2
  for (let i = 1; i < points.length; i++) {
    const seg = dist(points[i - 1], points[i])
    if (seg >= left) return toward(points[i - 1], points[i], left)
    left -= seg
  }
  return points[points.length - 1]
}
