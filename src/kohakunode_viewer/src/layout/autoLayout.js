/**
 * autoLayout.js — Simple topological-sort-based auto-layout for KirGraph nodes.
 *
 * Nodes that already have a non-zero position (x !== 0 || y !== 0) are left
 * in place.  Nodes at (0, 0) or missing coordinates are repositioned using a
 * BFS column layout derived from the graph's data edges.
 *
 * Layout parameters
 * -----------------
 *  Column width  : 280 px
 *  Row height    : 160 px
 *  Origin offset : (100, 100)
 */

const COL_WIDTH  = 280
const ROW_HEIGHT = 160
const ORIGIN_X   = 100
const ORIGIN_Y   = 100

/**
 * Assign x/y positions to nodes that don't have them yet.
 *
 * @param {object[]} nodes
 *   Array of node objects (shape from kirgraphToGraph). Each node has at
 *   least: { id, x, y, dataPorts?, controlPorts? }.
 *   The function mutates copies — the originals are NOT modified.
 *
 * @param {object[]} edges
 *   Array of edge objects. Each edge has at least:
 *   { fromNodeId, toNodeId, portType: 'data'|'control' }
 *   (the shape produced by kirgraphToGraph).
 *
 * @returns {object[]} New array of node objects with updated x / y values.
 */
export function autoLayout(nodes, edges) {
  if (!nodes || nodes.length === 0) return []

  // Build a set of node ids that already have explicit positions.
  const nodeIds = new Set(nodes.map(n => n.id))

  // Identify nodes that need placement (x === 0 && y === 0, or missing coords).
  const needsLayout = new Set(
    nodes
      .filter(n => !hasPosition(n))
      .map(n => n.id)
  )

  if (needsLayout.size === 0) {
    // All nodes positioned — nothing to do.
    return nodes.map(n => ({ ...n }))
  }

  // ── Build adjacency from data edges only (control edges represent execution
  //    order which may differ from the useful left-to-right data flow layout).
  //    We include all edge types so isolated control-only subgraphs are placed.
  const outEdges = new Map() // nodeId -> Set<nodeId>
  const inDegree = new Map() // nodeId -> number (among nodes needing layout)

  for (const id of needsLayout) {
    outEdges.set(id, new Set())
    inDegree.set(id, 0)
  }

  for (const edge of edges) {
    const src = edge.fromNodeId
    const dst = edge.toNodeId
    if (!needsLayout.has(src) || !needsLayout.has(dst)) continue
    if (!outEdges.get(src).has(dst)) {
      outEdges.get(src).add(dst)
      inDegree.set(dst, (inDegree.get(dst) ?? 0) + 1)
    }
  }

  // ── BFS topological level assignment ────────────────────────────────────────
  // level[id] = column index (depth from the nearest root)
  const level = new Map()
  const queue = []

  for (const [id, deg] of inDegree) {
    if (deg === 0) {
      queue.push(id)
      level.set(id, 0)
    }
  }

  let head = 0
  while (head < queue.length) {
    const cur = queue[head++]
    const curLevel = level.get(cur)
    for (const next of (outEdges.get(cur) ?? [])) {
      const existing = level.get(next) ?? -1
      if (curLevel + 1 > existing) {
        level.set(next, curLevel + 1)
      }
      inDegree.set(next, inDegree.get(next) - 1)
      if (inDegree.get(next) === 0) {
        queue.push(next)
      }
    }
  }

  // ── Handle cycles: any node not yet assigned a level goes in the next column
  let maxLevel = 0
  for (const [, l] of level) maxLevel = Math.max(maxLevel, l)

  for (const id of needsLayout) {
    if (!level.has(id)) {
      level.set(id, maxLevel + 1)
    }
  }

  // ── Group nodes by column, assign row within each column ────────────────────
  const columns = new Map() // colIndex -> [nodeId, ...]
  for (const [id, col] of level) {
    if (!columns.has(col)) columns.set(col, [])
    columns.get(col).push(id)
  }

  // Preserve deterministic ordering within each column by sorting node ids.
  for (const [, list] of columns) list.sort()

  // Build a position map for nodes that need layout.
  const positions = new Map() // nodeId -> { x, y }
  for (const [col, list] of columns) {
    list.forEach((id, row) => {
      positions.set(id, {
        x: ORIGIN_X + col * COL_WIDTH,
        y: ORIGIN_Y + row * ROW_HEIGHT,
      })
    })
  }

  // ── Return updated node array ────────────────────────────────────────────────
  return nodes.map(n => {
    if (!needsLayout.has(n.id)) return { ...n }
    const pos = positions.get(n.id)
    return { ...n, x: pos.x, y: pos.y }
  })
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Returns true if a node has a non-default position stored.
 * (0, 0) is treated as "not positioned" because that is the default
 * produced by kirgraphToGraph when the .kirgraph has no meta.pos.
 */
function hasPosition(node) {
  const x = node.x ?? 0
  const y = node.y ?? 0
  return x !== 0 || y !== 0
}
