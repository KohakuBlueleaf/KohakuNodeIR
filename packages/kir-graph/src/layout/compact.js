/**
 * Compaction of a drawn layout whose flow runs down, after ELK's placement:
 * every block (a top-level element with all it holds, a statement with its
 * satellites) slides up, control wires running down are straightened (the
 * trunk first), and blocks slide left, as far as each can. Blocks joined by a
 * straight control wire move sideways together, so the trunk stays straight.
 * Wires follow a move by stretching the segments at their moved ends; a
 * control wire takes its plainest route (down, across, down) where that runs
 * through no box, and the runs sharing a gap between two rows are re-spaced in
 * the order with the fewest crossings. A move is kept only when the flow order
 * holds (a control target stays below its source), no box comes near another
 * block's box, no wire runs through a box, every end segment keeps its
 * heading, and no new wire crossing appears.
 * Wires jumping back are left out of that until the blocks have settled, then
 * get the nearest clear lane outside, and the blocks settle once more.
 * `band` keeps that much more room between blocks one above another (where an
 * element's overlay marks are drawn).
 */

const GAP = 24
const CLEAR = 4
const MIN_END = 8
const FLOW_GAP = 24
const ROUNDS = 3
// A wire jumping back: its stub out of a pin, and the spacing of the lanes wires jumping back run in
const STUB = 16
const LANE = 8
const EPS = 0.5
// A step this small between a pin and the route ELK drew to its port is snapped straight
const ALIGN = 2

const add = (p, d) => ({ x: p.x + d.x, y: p.y + d.y })
const vertical = (a, b) => Math.abs(a.x - b.x) < ALIGN
const level = (a, b) => Math.abs(a.y - b.y) < ALIGN
const same = (a, b) => vertical(a, b) && level(a, b)

/**
 * A route without repeated points or points in the middle of a straight run,
 * every segment exactly horizontal or vertical (a near-straight step is
 * snapped, the ends kept where they are), so its segments alternate.
 */
function simplify(route) {
  const out = []
  for (const p of route) {
    if (out.length && same(out[out.length - 1], p)) continue
    if (out.length >= 2) {
      const [a, b] = out.slice(-2)
      if ((vertical(a, b) && vertical(b, p)) || (level(a, b) && level(b, p))) out.pop()
    }
    out.push({ x: p.x, y: p.y })
  }
  const last = out.length - 1
  for (let i = 0; i < last; i++) {
    const [a, b] = [out[i], out[i + 1]]
    const axis = vertical(a, b) ? "x" : level(a, b) ? "y" : null
    if (axis && i + 1 === last) a[axis] = b[axis]
    else if (axis) b[axis] = a[axis]
  }
  return out
}

/** `route` with its start moved by `ds` and its end by `dt`, kept orthogonal by moving the bends next to each end. */
function stretch(route, ds, dt) {
  const r = simplify(route)
  const n = r.length
  if (n < 2) return r.map((p) => add(p, ds))
  const a = add(r[0], ds)
  const b = add(r[n - 1], dt)
  if (n === 2) {
    if (vertical(a, b) || level(a, b)) return simplify([a, b])
    // The step sits next to the end that moved, a stub from it; midway when both moved
    const moved = (d) => d.x || d.y
    const at = (u, v, end) => (moved(ds) && moved(dt) ? (u + v) / 2 : end + Math.sign(u - end || v - end) * Math.min(STUB, Math.abs(u - v) / 2))
    if (vertical(r[0], r[1])) {
      const my = moved(dt) && !moved(ds) ? at(a.y, b.y, b.y) : at(b.y, a.y, a.y)
      return [a, { x: a.x, y: my }, { x: b.x, y: my }, b]
    }
    const mx = moved(dt) && !moved(ds) ? at(a.x, b.x, b.x) : at(b.x, a.x, a.x)
    return [a, { x: mx, y: a.y }, { x: mx, y: b.y }, b]
  }
  const p = r.map((q) => ({ ...q }))
  p[0] = a
  p[n - 1] = b
  if (vertical(r[0], r[1])) p[1].x = a.x
  else p[1].y = a.y
  if (vertical(r[n - 2], r[n - 1])) p[n - 2].x = b.x
  else p[n - 2].y = b.y
  // An end moved past its bend drags the run beyond the bend along, an end segment's length behind it
  if (n >= 4) {
    drag(p, r, 0, 1, 2, ds)
    drag(p, r, n - 1, n - 2, n - 3, dt)
  }
  return p
}

/** Where the end segment `p[e]`-`p[b]` turned round or got short, move the bend `b` and the next point `c` back to an end segment's length from `p[e]`. */
function drag(p, r, e, b, c, d) {
  if (!d.x && !d.y) return
  const h0 = heading(r[e], r[b])
  const h1 = heading(p[e], p[b])
  const len = Math.hypot(p[b].x - p[e].x, p[b].y - p[e].y)
  if (h0.x === h1.x && h0.y === h1.y && len >= MIN_END) return
  const keep = Math.max(2 * MIN_END, Math.min(Math.hypot(r[b].x - r[e].x, r[b].y - r[e].y), 2 * MIN_END))
  if (h0.y) p[b].y = p[c].y = p[e].y + h0.y * keep
  else p[b].x = p[c].x = p[e].x + h0.x * keep
}

/** The unit heading of the segment from `a` to `b`. */
const heading = (a, b) => ({ x: Math.sign(Math.round(b.x - a.x)), y: Math.sign(Math.round(b.y - a.y)) })

/** Whether the end segments of `next` run the way those of `before` do, each at least MIN_END long. */
function endsHold(before, next) {
  const r = simplify(before)
  const q = simplify(next)
  if (r.length < 2 || q.length < 2) return true
  const pairs = [
    [r[0], r[1], q[0], q[1]],
    [r[r.length - 1], r[r.length - 2], q[q.length - 1], q[q.length - 2]],
  ]
  for (const [r0, r1, q0, q1] of pairs) {
    const h0 = heading(r0, r1)
    const h1 = heading(q0, q1)
    if (h0.x !== h1.x || h0.y !== h1.y) return false
    if (Math.hypot(q1.x - q0.x, q1.y - q0.y) < MIN_END && Math.hypot(r1.x - r0.x, r1.y - r0.y) >= MIN_END) return false
  }
  return true
}

const segments = (route) => route.slice(1).map((p, i) => [route[i], p])

/** Whether the axis-aligned segment `[a, b]` enters box `o` grown by `m` (shrunk when negative). */
function hits([a, b], o, m) {
  const x0 = Math.min(a.x, b.x)
  const x1 = Math.max(a.x, b.x)
  const y0 = Math.min(a.y, b.y)
  const y1 = Math.max(a.y, b.y)
  return x1 > o.x - m && x0 < o.x + o.w + m && y1 > o.y - m && y0 < o.y + o.h + m
}

/** Proper crossings between the segments of two routes (a horizontal run through a vertical one). */
function crossings(r1, r2) {
  let n = 0
  for (const [a, b] of segments(r1))
    for (const [c, d] of segments(r2)) {
      const [h, v] = vertical(a, b) ? [[c, d], [a, b]] : [[a, b], [c, d]]
      if (!vertical(v[0], v[1]) || vertical(h[0], h[1])) continue
      const x = v[0].x
      const y = h[0].y
      if (x > Math.min(h[0].x, h[1].x) + EPS && x < Math.max(h[0].x, h[1].x) - EPS && y > Math.min(v[0].y, v[1].y) + EPS && y < Math.max(v[0].y, v[1].y) - EPS) n++
    }
  return n
}

/** Every order of `list`, `list` itself first. */
function* permutations(list) {
  if (list.length <= 1) {
    yield list
    return
  }
  for (let i = 0; i < list.length; i++) for (const rest of permutations([...list.slice(0, i), ...list.slice(i + 1)])) yield [list[i], ...rest]
}

const overlapX = (a, b, m) => a.x < b.x + b.w + m && b.x < a.x + a.w + m
const overlapY = (a, b, m) => a.y < b.y + b.h + m && b.y < a.y + a.h + m

/** The layout compacted up and left (see the module comment). */
export function compactLayout(layout, { band = 0 } = {}) {
  const gapY = GAP + band
  const flowGap = FLOW_GAP + band
  const clash = (b, o) => overlapX(b, o, GAP) && overlapY(b, o, gapY)
  const nodes = layout.nodes.map((b) => ({ ...b }))
  const regions = layout.regions.map((b) => ({ ...b }))
  const all = [...nodes, ...regions]
  const byId = new Map(all.map((b) => [b.id, b]))
  const rootMap = new Map()
  for (const start of all) {
    let b = start
    if (b.host) b = byId.get(b.host)
    while (b?.parent && byId.has(b.parent)) b = byId.get(b.parent)
    rootMap.set(start.id, b?.id ?? null)
  }
  const rootOf = (id) => rootMap.get(id) ?? null
  const blocks = new Map()
  for (const b of all) {
    const k = rootOf(b.id)
    if (!blocks.has(k)) blocks.set(k, { id: k, boxes: [], leaves: [] })
    const blk = blocks.get(k)
    // Boxes that keep other blocks off: the top-level ones; wires stay clear of every node box
    if (!b.parent || b.host) blk.boxes.push(b)
    if (nodes.includes(b)) blk.leaves.push(b)
  }
  const edges = layout.edges.map((e) => ({ ...e, route: e.route && simplify(e.route), sb: rootOf(e.source), tb: rootOf(e.target) }))
  const touching = new Map([...blocks.keys()].map((k) => [k, []]))
  for (const e of edges) {
    if (!e.route) continue
    touching.get(e.sb)?.push(e)
    if (e.tb !== e.sb) touching.get(e.tb)?.push(e)
  }
  const leaves = nodes
  const minX = Math.min(...all.map((b) => b.x))
  // While loose, wires that jump back are neither obstacles nor counted: they get lanes of their own afterwards
  let loose = true
  const counts = (e) => !(loose && e.back)

  /** The routes of the wires at group `g` after it moves by `d`, or null when the move breaks a rule. */
  function trial(g, d) {
    const moved = new Set()
    for (const k of g) for (const b of blocks.get(k).boxes) moved.add(b)
    const shifted = (b) => (moved.has(b) || g.has(rootOf(b.id)) ? { ...b, x: b.x + d.x, y: b.y + d.y } : b)
    const mine = [...g].flatMap((k) => blocks.get(k).boxes).map(shifted)
    for (const [k, blk] of blocks) {
      if (g.has(k)) continue
      for (const o of blk.boxes) for (const b of mine) if (clash(b, o)) return null
    }
    const touched = new Set([...g].flatMap((k) => touching.get(k)))
    const routes = new Map()
    for (const e of touched) {
      const ins = g.has(e.sb)
      const outs = g.has(e.tb)
      const r = ins && outs ? e.route.map((p) => add(p, d)) : stretch(e.route, ins ? d : { x: 0, y: 0 }, outs ? d : { x: 0, y: 0 })
      if (!(ins && outs) && counts(e) && !endsHold(e.route, r)) return null
      const drop = (q) => q[q.length - 1].y - q[0].y
      if (e.kind === "ctrl" && !e.back && !e.wrapped && !(ins && outs) && drop(r) < Math.min(drop(e.route), flowGap)) return null
      routes.set(e, r)
    }
    const placed = leaves.map(shifted)
    for (const [e, r] of routes) {
      const p = plain(e, r, placed)
      if (p) routes.set(e, p)
    }
    respace(routes)
    for (const [e, r] of routes) if (counts(e)) for (const s of segments(r)) for (const o of placed) if (hits(s, o, -1)) return null
    const mineLeaves = [...g].flatMap((k) => blocks.get(k).leaves).map(shifted)
    const changed = [...routes.keys()].filter(counts)
    let before = 0
    let after = 0
    for (const e of edges) {
      if (!e.route || routes.has(e) || !counts(e)) continue
      for (const s of segments(e.route)) for (const o of mineLeaves) if (hits(s, o, CLEAR)) return null
      for (const t of changed) {
        before += crossings(t.route, e.route)
        after += crossings(routes.get(t), e.route)
      }
    }
    changed.forEach((a, i) =>
      changed.slice(i + 1).forEach((b) => {
        before += crossings(a.route, b.route)
        after += crossings(routes.get(a), routes.get(b))
      }),
    )
    return after > before ? null : routes
  }

  /**
   * The plainest route for a forward control wire, when it runs through no
   * node box: leaving down onto a top pin, down, across just over the target
   * and down; leaving sideways onto a top pin beyond, across then down.
   */
  function plain(e, r, placed) {
    if (e.kind !== "ctrl" || e.back || e.wrapped || r.length < 2) return null
    const s = r[0]
    const t = r[r.length - 1]
    const hs = heading(r[0], r[1])
    const ht = heading(t, r[r.length - 2])
    if (ht.y !== -1 || t.y - s.y < 2 * MIN_END) return null
    let route = null
    if (hs.y === 1) {
      const y = t.y - Math.min(2 * MIN_END, (t.y - s.y) / 2)
      route = simplify([s, { x: s.x, y }, { x: t.x, y }, t])
    } else if (hs.x && Math.sign(t.x - s.x) === hs.x && Math.abs(t.x - s.x) >= MIN_END) route = [s, { x: t.x, y: s.y }, t]
    if (!route || route.length >= r.length) return null
    for (const seg of segments(route)) for (const o of placed) if (hits(seg, o, -1)) return null
    return route
  }

  /** Every forward control wire with a plainer route that runs through no box and crosses no more wires takes it. */
  function tidy() {
    for (const e of edges) {
      if (!e.route || !counts(e)) continue
      const r = plain(e, e.route, leaves)
      if (!r) continue
      const others = edges.filter((o) => o !== e && o.route && counts(o))
      if (others.reduce((n, o) => n + crossings(r, o.route), 0) <= others.reduce((n, o) => n + crossings(e.route, o.route), 0)) e.route = r
    }
  }

  /** A wire's run between two rows (down from its source, across, down onto its target): its room and its span. */
  const runOf = (r) => {
    if (r.length !== 4) return null
    const [a, b, c, d] = r
    if (!vertical(a, b) || !level(b, c) || !vertical(c, d) || b.y <= a.y || d.y <= c.y) return null
    return { lo: a.y + MIN_END, hi: d.y - MIN_END, x0: Math.min(b.x, c.x), x1: Math.max(b.x, c.x) }
  }

  /**
   * The runs sharing a gap (room and span overlapping) with a run in `routes`
   * are put in the order with the fewest crossings and spread evenly over the
   * room they share; their routes join `routes`.
   */
  function respace(routes) {
    const current = (e) => routes.get(e) ?? e.route
    const list = edges.filter((e) => e.route && counts(e)).flatMap((e) => {
      const run = runOf(simplify(current(e)))
      return run ? [{ e, run }] : []
    })
    const parent = list.map((_, i) => i)
    const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])))
    list.forEach((a, i) =>
      list.forEach((b, j) => {
        if (j > i && a.run.lo < b.run.hi && b.run.lo < a.run.hi && a.run.x0 < b.run.x1 && b.run.x0 < a.run.x1) parent[find(i)] = find(j)
      }),
    )
    const clusters = new Map()
    list.forEach((x, i) => clusters.set(find(i), [...(clusters.get(find(i)) || []), x]))
    for (const cluster of clusters.values()) {
      if (cluster.length < 2 || cluster.length > 6 || !cluster.some((x) => routes.has(x.e))) continue
      const lo = Math.max(...cluster.map((x) => x.run.lo))
      const hi = Math.min(...cluster.map((x) => x.run.hi))
      if (hi - lo < 2) continue
      const n = cluster.length
      const step = Math.min(10, (hi - lo) / (n + 1))
      const ys = cluster.map((_, i) => (lo + hi) / 2 + (i - (n - 1) / 2) * step)
      const others = edges.filter((e) => e.route && counts(e) && !cluster.some((x) => x.e === e))
      const place = (order) => order.map((x, i) => [x.e, simplify(current(x.e)).map((p, k) => (k === 1 || k === 2 ? { x: p.x, y: ys[i] } : p))])
      const cost = (placed) =>
        placed.reduce((s, [e, r], i) => s + others.reduce((t, o) => t + crossings(r, current(o)), 0) + placed.slice(i + 1).reduce((t, [, q]) => t + crossings(r, q), 0), 0)
      let best = null
      const byY = [...cluster].sort((a, b) => simplify(current(a.e))[1].y - simplify(current(b.e))[1].y)
      for (const order of permutations(byY)) {
        const placed = place(order)
        const c = cost(placed)
        if (!best || c < best.c) best = { c, placed }
      }
      for (const [e, r] of best.placed) routes.set(e, r)
    }
  }

  function apply(g, d, routes) {
    for (const b of all) if (g.has(rootOf(b.id))) Object.assign(b, { x: b.x + d.x, y: b.y + d.y })
    for (const [e, r] of routes) {
      if (e.tailBox && g.has(e.sb)) e.tailBox = { ...e.tailBox, x: e.tailBox.x + d.x, y: e.tailBox.y + d.y }
      e.route = simplify(r)
    }
  }

  const box = (g) => {
    const list = [...g].flatMap((k) => blocks.get(k).boxes)
    const x = Math.min(...list.map((b) => b.x))
    const y = Math.min(...list.map((b) => b.y))
    return { x, y, w: Math.max(...list.map((b) => b.x + b.w)) - x, h: Math.max(...list.map((b) => b.y + b.h)) - y }
  }

  /**
   * Slide every group up (`axis` "y") or left ("x") to the farthest stop that
   * passes `trial`, no farther than `limit(group, its box)`: under or level with
   * another block, or short of a wire it may not cross.
   */
  function slide(groups, axis, limit) {
    let moved = false
    const order = [...groups].sort((a, b) => box(a)[axis] - box(b)[axis])
    for (const g of order) {
      const me = box(g)
      const stops = new Set([limit(g, me)])
      for (const [k, blk] of blocks) {
        if (g.has(k)) continue
        for (const o of blk.boxes) {
          // Up: under a box above, or level with the top of any box higher up (a row of siblings)
          if (axis === "y" && o.y < me.y) stops.add(me.y - o.y)
          if (axis === "y" && overlapX(me, o, GAP) && o.y + o.h <= me.y) stops.add(me.y - (o.y + o.h + gapY))
          if (axis === "x" && overlapY(me, o, gapY) && o.x + o.w <= me.x) stops.add(me.x - (o.x + o.w + GAP))
        }
      }
      // Wires not its own stop it too: a lane it may not cross
      for (const e of edges) {
        if (!e.route || !counts(e) || g.has(e.sb) || g.has(e.tb)) continue
        for (const [a, b] of segments(e.route)) {
          const run = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) }
          if (axis === "y" && level(a, b) && overlapX(me, run, 0) && run.y <= me.y) stops.add(me.y - (run.y + GAP / 2))
          if (axis === "x" && vertical(a, b) && overlapY(me, run, 0) && run.x <= me.x) stops.add(me.x - (run.x + GAP / 2))
        }
      }
      const cap = limit(g, me)
      for (const s of [...stops].filter((s) => s > EPS && s <= cap + EPS).sort((a, b) => b - a)) {
        const d = axis === "y" ? { x: 0, y: -s } : { x: -s, y: 0 }
        const routes = trial(g, d)
        if (!routes) continue
        apply(g, d, routes)
        moved = true
        break
      }
    }
    return moved
  }

  // Up: each block alone, no farther than its control sources allow
  const upLimit = (g, me) => {
    let cap = me.y - Math.min(...all.map((b) => b.y))
    for (const k of g)
      for (const e of touching.get(k))
        if (e.kind === "ctrl" && !e.back && !e.wrapped && g.has(e.tb) && !g.has(e.sb)) {
          const r = e.route
          cap = Math.min(cap, r[r.length - 1].y - r[0].y - flowGap)
        }
    return cap
  }
  // Left: blocks joined by a straight control wire go together
  const leftGroups = () => {
    const parent = new Map([...blocks.keys()].map((k) => [k, k]))
    const find = (k) => (parent.get(k) === k ? k : find(parent.get(k)))
    for (const e of edges)
      if (e.kind === "ctrl" && e.route && e.sb !== e.tb && e.route.every((p) => Math.abs(p.x - e.route[0].x) < EPS)) parent.set(find(e.sb), find(e.tb))
    const out = new Map()
    for (const k of blocks.keys()) out.set(find(k), (out.get(find(k)) || new Set()).add(k))
    return [...out.values()]
  }
  const leftLimit = (g, me) => me.x - minX

  const forward = (e) => e.kind === "ctrl" && !e.back && !e.wrapped && e.route && e.sb !== e.tb
  const straight = (e) => e.route.every((p) => Math.abs(p.x - e.route[0].x) < EPS)
  const leaves0 = (e) => heading(e.route[0], e.route[1])
  const arrives = (e) => heading(e.route[e.route.length - 1], e.route[e.route.length - 2])

  /**
   * The trunk: from every block nothing flows into, the control wire leaving
   * downward nearest the bottom centre of the element it leaves, one per block.
   */
  function trunk() {
    const into = new Set(edges.filter(forward).map((e) => e.tb))
    const seen = new Set()
    const out = new Set()
    const stack = [...blocks.keys()].filter((k) => !into.has(k))
    while (stack.length) {
      const k = stack.pop()
      if (seen.has(k)) continue
      seen.add(k)
      const centre = (e) => {
        const n = byId.get(e.source)
        return Math.abs(e.route[0].x - (n ? n.x + n.w / 2 : e.route[0].x))
      }
      const down = touching.get(k).filter((e) => forward(e) && e.sb === k && leaves0(e).y === 1)
      const e = down.sort((a, b) => centre(a) - centre(b))[0]
      if (!e) continue
      out.add(e)
      stack.push(e.tb)
    }
    return out
  }

  /**
   * Straighten control wires that run down from a bottom pin onto a top pin:
   * trunk wires first (their target side moves), then the others (the side off
   * the trunk moves), so a join sits under the trunk and its arms come to it.
   */
  function align() {
    const main = trunk()
    const list = edges
      .filter((e) => forward(e) && leaves0(e).y === 1 && arrives(e).y === -1 && !straight(e))
      .sort((a, b) => main.has(b) - main.has(a) || a.route[0].y - b.route[0].y)
    let moved = false
    // The chain a block heads: it and the blocks under it joined by straight control wires
    const chain = (k, dir) => {
      const out = new Set([k])
      const stack = [k]
      while (stack.length) {
        const c = stack.pop()
        for (const x of touching.get(c)) {
          const [from, to] = dir > 0 ? [x.sb, x.tb] : [x.tb, x.sb]
          if (forward(x) && from === c && straight(x) && !out.has(to)) {
            out.add(to)
            stack.push(to)
          }
        }
      }
      return out
    }
    for (const e of list) {
      if (straight(e)) continue
      // The target carries the chain below it; the source the chain above it
      const gs = chain(e.sb, -1)
      const gt = chain(e.tb, 1)
      if ([...gs].some((k) => gt.has(k))) continue
      const s = e.route[0]
      const t = e.route[e.route.length - 1]
      const onTrunk = (g) => [...main].some((x) => g.has(x.sb) || g.has(x.tb))
      const target = [gt, { x: s.x - t.x, y: 0 }]
      const source = [gs, { x: t.x - s.x, y: 0 }]
      // A trunk wire moves its target only; any other wire moves its side off the trunk, else the other side
      const tries = main.has(e) ? [target] : onTrunk(gs) ? (onTrunk(gt) ? [] : [target]) : onTrunk(gt) ? [source] : [source, target]
      for (const [g, d] of tries) {
        const routes = trial(g, d)
        if (!routes) continue
        apply(g, d, routes)
        moved = true
        break
      }
    }
    return moved
  }

  /**
   * Every wire that jumps back runs in a lane of its own on the side its
   * target pin faces: the nearest x past both pins clear of every box and
   * lane over the wire's whole span, so the outermost one hugs the outline.
   * No block moves for it. Inner loops are routed first.
   */
  function routeBack() {
    const back = edges.filter((e) => e.back && !e.wrapped && e.route?.length >= 2 && e.sb !== e.tb)
    const span = (e) => Math.abs(e.route[0].y - e.route[e.route.length - 1].y)
    back.sort((a, b) => span(a) - span(b))
    const lanes = []
    for (const e of back) {
      const r = e.route
      const s = r[0]
      const t = r[r.length - 1]
      const hs = leaves0(e)
      const ht = arrives(e)
      const side = ht.x || hs.x || 1
      let s1 = { x: s.x + hs.x * STUB, y: s.y + hs.y * STUB }
      let t1 = { x: t.x + ht.x * STUB, y: t.y + ht.y * STUB }
      const y0 = Math.min(s.y, t.y, s1.y, t1.y)
      const y1 = Math.max(s.y, t.y, s1.y, t1.y)
      const inRange = (b) => b.y < y1 + CLEAR && b.y + b.h > y0 - CLEAR
      // The nearest x past both pins where a run down the whole span touches no box and no other lane
      const near = side > 0 ? Math.max(s1.x, t1.x) : Math.min(s1.x, t1.x)
      const boxes = leaves.filter(inRange)
      const free = (x) =>
        !boxes.some((b) => x > b.x - 2 * LANE && x < b.x + b.w + 2 * LANE) && !lanes.some((l) => l.y0 < y1 && l.y1 > y0 && Math.abs(l.x - x) < LANE)
      const stops = [near, ...boxes.map((b) => (side > 0 ? b.x + b.w : b.x) + side * 2 * LANE), ...lanes.map((l) => l.x + side * LANE)]
      const x = stops.filter((v) => side * (v - near) >= 0 && free(v)).sort((a, b) => side * (a - b))[0]
      if (x == null) continue
      // The legs between the pins and the lane drop clear of the boxes they would run through
      const clearLeg = (p, h) => {
        for (let i = 0; i < 20 && h.y; i++) {
          const leg = [p, { x, y: p.y }]
          const hit = leaves.find((b) => hits(leg, b, CLEAR))
          if (!hit) break
          p = { x: p.x, y: h.y > 0 ? hit.y + hit.h + 2 * CLEAR : hit.y - 2 * CLEAR }
        }
        return p
      }
      s1 = clearLeg(s1, hs)
      t1 = clearLeg(t1, ht)
      e.route = simplify([s, s1, { x, y: s1.y }, { x, y: t1.y }, t1, t])
      lanes.push({ x, y0, y1 })
    }
  }

  const rounds = () => {
    for (let i = 0; i < ROUNDS; i++) {
      const up = slide(
        [...blocks.keys()].map((k) => new Set([k])),
        "y",
        upLimit,
      )
      const lined = align()
      const left = slide(leftGroups(), "x", leftLimit)
      if (!up && !lined && !left) break
    }
  }
  tidy()
  rounds()
  routeBack()
  loose = false
  rounds()
  tidy()

  const out = edges.map(({ sb, tb, ...e }) => e)
  const bounds = { w: Math.max(0, ...all.map((b) => b.x + b.w)), h: Math.max(0, ...all.map((b) => b.y + b.h)) }
  return { ...layout, nodes, regions, edges: out, bounds }
}
