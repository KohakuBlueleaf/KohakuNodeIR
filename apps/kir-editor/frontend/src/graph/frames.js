/**
 * Control as boxing: the node view's `frames` style.
 *
 * No control wires are drawn. Statements run top to bottom inside framed
 * regions; each namespace, branch arm, loop body, `each` body, `@try` /
 * `@except` and `@dataflow` block is a region with a header naming it. The
 * regions come from `structure` (the graph's statements as graph -> text
 * reads them, each tagged with its node id), so the boxing always agrees
 * with the program text.
 *
 * Variable and literal pills sit beside the node they serve: reads and
 * literals on its left, writes on its right.
 */

import { shortLiteral } from "@/graph/literal"

const GAP_Y = 18
const GAP_X = 26
const SAT_GAP = 8
const HEAD = 26
const PAD = 14

const CONTROLLERS = new Set(["branch", "switch", "each", "parallel"])

/** Labels a controller statement enters, with a region title for each. */
function armsOf(s) {
  switch (s.type) {
    case "branch":
      return [
        [s.true_label, `if true → ${s.true_label}`],
        [s.false_label, `else → ${s.false_label}`],
      ]
    case "switch":
      return [
        ...s.cases.map(([v, label]) => [label, `case ${shortLiteral(v, 12)} → ${label}`]),
        ...(s.default ? [[s.default, `default → ${s.default}`]] : []),
      ]
    case "parallel":
      return s.labels.map((l) => [l, `parallel · ${l}`])
    case "each": {
      const names = [s.item || "_", ...(s.has_index ? [s.index || "_"] : [])].join(", ")
      return [[s.label, `each ${names} · ${s.label}`]]
    }
    default:
      return []
  }
}

/**
 * Lay out one graph as frames. `geometry(node)` gives node sizes. Resolves
 * nothing asynchronously; returns the layout object the canvases use plus
 * `regions` (drawn behind the nodes) and `hidden` (nodes not drawn).
 */
export function framesLayout(graph, statements, geometry) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const size = (id) => {
    const g = geometry(byId.get(id))
    return { w: g.w, h: g.h }
  }
  // Satellites: reads and literals go left of the node they feed, writes right of the node feeding them.
  const leftOf = new Map()
  const rightOf = new Map()
  const satellite = new Set()
  for (const n of graph.nodes) {
    if (n.kind === "get" || n.kind === "value") {
      const e = graph.edges.find((x) => x.kind === "data" && x.from.node === n.id)
      if (e) {
        satellite.add(n.id)
        leftOf.set(e.to.node, [...(leftOf.get(e.to.node) || []), n.id])
      }
    } else if (n.kind === "set") {
      const e = graph.edges.find((x) => x.kind === "data" && x.to.node === n.id)
      if (e) {
        satellite.add(n.id)
        rightOf.set(e.from.node, [...(rightOf.get(e.from.node) || []), n.id])
      }
    }
  }

  const positions = {}
  const regions = []
  const placed = new Set()

  // A row: satellites | node | satellites. Returns its size; `at` places it.
  function rowBox(id) {
    const node = size(id)
    const col = (ids) => {
      const sizes = ids.map(size)
      return {
        w: Math.max(0, ...sizes.map((s) => s.w)),
        h: sizes.reduce((a, s) => a + s.h, 0) + Math.max(0, ids.length - 1) * SAT_GAP,
        sizes,
      }
    }
    const L = col(leftOf.get(id) || [])
    const R = col(rightOf.get(id) || [])
    const w = (L.w ? L.w + GAP_X : 0) + node.w + (R.w ? R.w + GAP_X : 0)
    const h = Math.max(node.h, L.h, R.h)
    return {
      w,
      h,
      at(x, y) {
        const nx = x + (L.w ? L.w + GAP_X : 0)
        positions[id] = { x: nx, y }
        placed.add(id)
        let ly = y
        ;(leftOf.get(id) || []).forEach((s, i) => {
          positions[s] = { x: nx - GAP_X - L.sizes[i].w, y: ly }
          placed.add(s)
          ly += L.sizes[i].h + SAT_GAP
        })
        let ry = y
        ;(rightOf.get(id) || []).forEach((s, i) => {
          positions[s] = { x: nx + node.w + GAP_X, y: ry }
          placed.add(s)
          ry += R.sizes[i].h + SAT_GAP
        })
      },
    }
  }

  // A framed region around a sequence.
  function regionBox(title, kind, items, depth) {
    const inner = seqBox(items, depth + 1)
    const w = Math.max(200, inner.w + 2 * PAD, title.length * 6.6 + 40)
    const h = HEAD + inner.h + PAD + (items.length ? 0 : 20)
    return {
      w,
      h,
      at(x, y) {
        regions.push({ id: `region:${regions.length}:${title}`, x, y, w, h, title, kind, depth, last: lastNode(items) })
        inner.at(x + PAD, y + HEAD)
      },
    }
  }

  // Boxes side by side (the arms of one branch, switch, parallel or try).
  function armsBox(boxes) {
    const w = boxes.reduce((a, b) => a + b.w, 0) + Math.max(0, boxes.length - 1) * GAP_X
    const h = Math.max(0, ...boxes.map((b) => b.h))
    return {
      w,
      h,
      at(x, y) {
        let ax = x
        for (const b of boxes) {
          b.at(ax, y)
          ax += b.w + GAP_X
        }
      },
    }
  }

  function lastNode(items) {
    for (let i = items.length - 1; i >= 0; i--) {
      const id = items[i].meta?.node_id
      const n = id && byId.get(id)
      if (n && (n.ctrl_out || []).includes("out") && (n.kind === "call" || n.kind === "assign")) return id
    }
    return null
  }

  function seqBox(items, depth) {
    const boxes = []
    for (let i = 0; i < items.length; i++) {
      const s = items[i]
      const id = s.meta?.node_id
      if (s.type === "namespace") {
        boxes.push(regionBox(`label ${s.label}`, "namespace", s.body, depth))
        continue
      }
      if (s.type === "jump") {
        const next = items[i + 1]
        if (id && next?.type === "namespace" && next.label === s.label) {
          boxes.push(regionBox(`loop ${s.label}`, "loop", next.body, depth))
          i++
        }
        continue // a jump back to a loop is the end of its region
      }
      if (s.type === "dataflow") {
        boxes.push(regionBox("@dataflow · ordered by data", "dataflow", s.body, depth))
        continue
      }
      if (s.type === "try") {
        if (id && byId.has(id)) boxes.push(rowBox(id))
        boxes.push(
          armsBox([
            regionBox("try", "try", s.body, depth),
            regionBox(s.error_name ? `except ${s.error_name}` : "except", "except", s.handler, depth),
          ]),
        )
        continue
      }
      if (id && byId.has(id)) boxes.push(rowBox(id))
      if (CONTROLLERS.has(s.type)) {
        const arms = armsOf(s)
        const claimed = []
        let j = i + 1
        while (j < items.length && items[j].type === "namespace" && arms.some(([l]) => l === items[j].label)) {
          claimed.push(items[j])
          j++
        }
        if (claimed.length) {
          const titled = claimed.map((ns) => regionBox(arms.find(([l]) => l === ns.label)[1], s.type, ns.body, depth))
          boxes.push(armsBox(titled))
          i = j - 1
        }
      }
    }
    const w = Math.max(0, ...boxes.map((b) => b.w))
    const h = boxes.reduce((a, b) => a + b.h, 0) + Math.max(0, boxes.length - 1) * GAP_Y
    return {
      w,
      h,
      at(x, y) {
        let by = y
        for (const b of boxes) {
          b.at(x, by)
          by += b.h + GAP_Y
        }
      },
    }
  }

  const top = []
  const inputs = graph.nodes.find((n) => n.kind === "inputs")
  const outputs = graph.nodes.find((n) => n.kind === "outputs")
  if (inputs) top.push(rowBox(inputs.id))
  top.push(seqBox(statements || [], 0))
  if (outputs) top.push(rowBox(outputs.id))
  let y = 0
  let width = 0
  for (const b of top) {
    b.at(0, y)
    y += b.h + GAP_Y
    width = Math.max(width, b.w)
  }

  // Merges are drawn as their regions; anything else left over goes in a column on the right.
  const hidden = new Set(graph.nodes.filter((n) => n.kind === "merge" || n.kind === "dataflow").map((n) => n.id))
  let ly = 0
  for (const n of graph.nodes) {
    if (placed.has(n.id) || hidden.has(n.id)) continue
    const s = size(n.id)
    positions[n.id] = { x: width + 80, y: ly }
    ly += s.h + GAP_Y
  }
  return { positions, absolute: { ...positions }, frames: {}, routes: {}, regions, hidden, last: lastNode(statements || []) }
}
