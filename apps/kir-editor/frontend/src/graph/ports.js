/** Port and edge identities shared by every graph view. */

/** Handle id of a port: `<flow>:<dir>:<name>` (flow "data" or "ctrl", dir "in" or "out"). */
export const handleId = (flow, dir, name) => `${flow}:${dir}:${name}`

export function parseHandle(id) {
  const [flow, dir, ...rest] = id.split(":")
  return { flow, dir, name: rest.join(":") }
}

/** The free `in_<n>` slot a merge offers for one more incoming path. */
export const mergeSlot = (node) => `in_${(node.ctrl_in || []).length}`

export const edgeKey = (e) => `${e.kind}|${e.from.node}|${e.from.port}|${e.to.node}|${e.to.port}`

export const sourceHandle = (e) => handleId(e.kind === "ctrl" ? "ctrl" : "data", "out", e.from.port)
export const targetHandle = (e) => handleId(e.kind === "ctrl" ? "ctrl" : "data", "in", e.to.port)

/** A control edge closing a loop: into a labelled merge (a jump back), or into an `each` node's `next`. */
export function isBackEdge(e, byId) {
  if (e.kind !== "ctrl") return false
  const target = byId.get(e.to.node)
  if (["each", "collect"].includes(target?.kind)) return e.to.port === "next"
  if (target?.kind !== "merge" || !target.props?.label) return false
  // The first entry into a loop merge comes from before the loop; the others come back to it.
  return e.to.port !== "in_0"
}

/** Map member node id -> dataflow node id. */
export function membership(graph) {
  const out = new Map()
  for (const n of graph.nodes)
    if (n.kind === "dataflow") for (const m of n.props?.members || []) out.set(m, n.id)
  return out
}

/** The type a data edge carries: its source port's, else its target port's. */
export function edgeType(e, byId) {
  const src = (byId.get(e.from.node)?.outputs || []).find((p) => p.port === e.from.port)
  const dst = (byId.get(e.to.node)?.inputs || []).find((p) => p.port === e.to.port)
  return src?.type || dst?.type || null
}
