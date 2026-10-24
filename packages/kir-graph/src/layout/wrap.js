/**
 * Macro columns for a layout whose flow runs down: the drawing is cut between
 * top-level bands (runs of elements with a horizontal gap above and below, so
 * no statement or region box is ever split) into columns placed side by side,
 * as many as bring the whole near a target aspect ratio. Each cut is taken
 * where the fewest wires cross it. A wire between columns runs out through
 * the empty row under its source's band into the gutter, over the top in a
 * lane of its own, and down onto its target (through the gutter and the row
 * over the target's band when the target is not at the top of its column);
 * between neighbouring columns it stays in the gutter they share.
 */

const COLUMN_GAP = 48
const LANE = 8
const STUB = 14
const BAND_GAP = 4
// Offset of a wire's run through the empty row between two bands (layers are 40 apart)
const GAP_ROW = 12
// A drawing no taller than this stays one column, whatever its aspect
const MIN_WRAP_HEIGHT = 720

/** The bands of a layout: [top, bottom] spans of its top-level elements, merged where they touch. */
function bands(boxes) {
  const spans = boxes.map((b) => [b.y, b.y + b.h]).sort((a, b) => a[0] - b[0])
  const out = []
  for (const [top, bottom] of spans) {
    const last = out[out.length - 1]
    if (last && top < last[1] + BAND_GAP) last[1] = Math.max(last[1], bottom)
    else out.push([top, bottom])
  }
  return out
}

/** The band index each element belongs to, by its top-level ancestor. */
function bandOf(layout, spans) {
  const byId = new Map([...layout.nodes, ...layout.regions].map((b) => [b.id, b]))
  const root = (b) => {
    while (b.parent && byId.has(b.parent)) b = byId.get(b.parent)
    return b
  }
  const index = (y) => spans.findIndex(([top, bottom]) => y >= top - 0.5 && y <= bottom + 0.5)
  const out = new Map()
  for (const b of byId.values()) out.set(b.id, index(root(b).y))
  return out
}

/** Cut `n` bands into `k` columns of near-equal height, each cut where the fewest wires cross. */
function cuts(spans, k, crossing) {
  const total = spans[spans.length - 1][1] - spans[0][0]
  const target = total / k
  const out = []
  let start = spans[0][0]
  for (let c = 1; c < k; c++) {
    let best = null
    for (let i = 1; i < spans.length; i++) {
      if (out.length && i <= out[out.length - 1]) continue
      const height = spans[i][0] - start
      if (height < target * 0.5 || height > target * 1.5) continue
      const score = crossing(i) * target * 0.3 + Math.abs(height - target)
      if (!best || score < best.score) best = { i, score }
    }
    if (!best) {
      const i = spans.findIndex(([top], j) => j > (out[out.length - 1] ?? 0) && top - start >= target)
      if (i <= 0) break
      best = { i }
    }
    out.push(best.i)
    start = spans[best.i][0]
  }
  return out
}

/** The layout cut into macro columns near aspect ratio `aspect` (width over height). */
export function wrapColumns(layout, aspect) {
  const tops = [...layout.nodes, ...layout.regions].filter((b) => !b.parent)
  if (!tops.length) return layout
  const spans = bands(tops)
  const total = spans[spans.length - 1][1] - spans[0][0]
  const width = layout.bounds.w
  if (total <= MIN_WRAP_HEIGHT) return layout
  const k = Math.min(spans.length, Math.max(1, Math.ceil(Math.sqrt((aspect * total) / Math.max(1, width)) - 0.35)))
  if (k < 2) return layout

  const band = bandOf(layout, spans)
  const edgeBands = layout.edges.map((e) => [band.get(e.source), band.get(e.target)])
  const crossing = (i) => edgeBands.filter(([a, b]) => a != null && b != null && Math.min(a, b) < i && Math.max(a, b) >= i).length
  const at = cuts(spans, k, crossing)
  // As many columns as cuts were found, which may be fewer than asked for
  if (!at.length) return layout
  const starts = [0, ...at]
  const column = (b) => {
    let c = 0
    while (c + 1 < starts.length && b >= starts[c + 1]) c++
    return c
  }
  const top0 = spans[0][0]
  // Each column starts a gap after the right edge of what the previous one holds, not of the whole drawing
  const extent = starts.map(() => [Infinity, -Infinity])
  const widen = (c, x0, x1) => {
    extent[c][0] = Math.min(extent[c][0], x0)
    extent[c][1] = Math.max(extent[c][1], x1)
  }
  for (const b of [...layout.nodes, ...layout.regions]) widen(column(band.get(b.id) ?? 0), b.x, b.x + b.w)
  layout.edges.forEach((e, i) => {
    const [a, b] = edgeBands[i].map((x) => column(x ?? 0))
    if (a === b && e.route) for (const p of e.route) widen(a, p.x, p.x)
  })
  const shift = []
  starts.forEach((s, c) => {
    const dx = c === 0 ? 0 : extent[c - 1][1] + shift[c - 1].dx + COLUMN_GAP - extent[c][0]
    shift.push({ dx, dy: top0 - spans[s][0] })
  })
  const edgeOf = (c, side) => (side > 0 ? extent[c][1] : extent[c][0]) + shift[c].dx
  const move = (b) => {
    const s = shift[column(band.get(b.id) ?? 0)]
    return { ...b, x: b.x + s.dx, y: b.y + s.dy }
  }
  const nodes = layout.nodes.map(move)
  const regions = layout.regions.map(move)
  const height = Math.max(...[...nodes, ...regions].map((b) => b.y + b.h))

  // Wires within a column move with it; wires between columns run through the gutters and over the top
  const bandTop = (i) => spans[i][0] + shift[column(i)].dy
  const bandBottom = (i) => spans[i][1] + shift[column(i)].dy
  const firstOfColumn = new Set(starts)
  const laneOf = new Map()
  const edges = layout.edges.map((e, i) => {
    if (!e.route) return e
    const [ba, bb] = edgeBands[i].map((x) => x ?? 0)
    const [a, b] = [column(ba), column(bb)]
    if (a === b) return { ...e, route: e.route.map((p) => ({ x: p.x + shift[a].dx, y: p.y + shift[a].dy })) }
    const lane = laneOf.size
    laneOf.set(e.id, lane)
    const s = { x: e.route[0].x + shift[a].dx, y: e.route[0].y + shift[a].dy }
    const t = { x: e.route[e.route.length - 1].x + shift[b].dx, y: e.route[e.route.length - 1].y + shift[b].dy }
    const leave = heading(e.route)
    const arrive = heading([...e.route].reverse())
    const gutterOut = gutter(edgeOf(a, b > a ? 1 : -1), b > a ? 1 : -1, lane)
    const gutterIn = gutter(edgeOf(b, b > a ? -1 : 1), b > a ? -1 : 1, lane)
    const laneY = top0 - 2 * STUB - lane * LANE
    const row = GAP_ROW + (lane % 3) * 4
    const route = [s]
    const outSide = b > a ? 1 : -1
    // Leaving downward: into the empty row under the source's band first; sideways away from the gutter:
    // round the band on the side the wire goes on to (over it toward the lane, or a target higher up)
    if (leave.y > 0) route.push({ x: s.x, y: bandBottom(ba) + row }, { x: gutterOut, y: bandBottom(ba) + row })
    else if (leave.x && leave.x !== outSide) {
      const sx = s.x + leave.x * STUB
      const over = Math.abs(a - b) !== 1 || bandTop(bb) < bandTop(ba)
      const y = over ? bandTop(ba) - row : bandBottom(ba) + row
      route.push({ x: sx, y: s.y }, { x: sx, y }, { x: gutterOut, y })
    } else route.push({ x: s.x + leave.x * STUB, y: s.y + leave.y * STUB }, { x: gutterOut, y: s.y + leave.y * STUB })
    // Neighbouring columns share one gutter: the wire stays in it, no lane over the top
    if (Math.abs(a - b) === 1) {
      const above = bandTop(bb) - row
      if (arrive.y < 0) route.push({ x: gutterOut, y: above }, { x: t.x, y: above })
      else if (arrive.x === -outSide) route.push({ x: gutterOut, y: t.y + arrive.y * STUB }, { x: t.x + arrive.x * STUB, y: t.y + arrive.y * STUB })
      else {
        const tx = t.x + arrive.x * STUB
        route.push({ x: gutterOut, y: above }, { x: tx, y: above }, { x: tx, y: t.y })
      }
      route.push(t)
      return { ...e, route, wrapped: true }
    }
    route.push({ x: gutterOut, y: laneY })
    // Arriving from above: straight down onto the top of a column, else through the row over the band
    if (arrive.y < 0 && firstOfColumn.has(bb)) route.push({ x: t.x, y: laneY })
    else if (arrive.y < 0) route.push({ x: gutterIn, y: laneY }, { x: gutterIn, y: bandTop(bb) - row }, { x: t.x, y: bandTop(bb) - row })
    else if (arrive.x && arrive.x !== -outSide) {
      const tx = t.x + arrive.x * STUB
      route.push({ x: gutterIn, y: laneY }, { x: gutterIn, y: bandTop(bb) - row }, { x: tx, y: bandTop(bb) - row }, { x: tx, y: t.y })
    } else {
      const into = { x: t.x + arrive.x * STUB, y: t.y + arrive.y * STUB }
      route.push({ x: gutterIn, y: laneY }, { x: gutterIn, y: into.y }, into)
    }
    route.push(t)
    return { ...e, route, wrapped: true }
  })
  return { ...layout, nodes, regions, edges, bounds: { w: edgeOf(starts.length - 1, 1), h: height }, columns: starts.length }
}

/** The unit direction a route first runs in from its first point (past any repeated points). */
function heading(route) {
  const p0 = route[0]
  const p1 = route.find((p) => Math.abs(p.x - p0.x) > 0.5 || Math.abs(p.y - p0.y) > 0.5) || p0
  const dx = p1.x - p0.x
  const dy = p1.y - p0.y
  return Math.abs(dy) >= Math.abs(dx) ? { x: 0, y: Math.sign(dy) } : { x: Math.sign(dx), y: 0 }
}

/** The x of a lane in the gutter on `side` (1 right, -1 left) of a column whose edge on that side is at `edge`. */
function gutter(edge, side, lane) {
  return edge + side * (COLUMN_GAP / 2 + ((lane % 4) - 1.5) * LANE)
}
