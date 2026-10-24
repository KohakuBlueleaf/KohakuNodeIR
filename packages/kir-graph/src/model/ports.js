/** Port and edge identities shared by every view. */

/** Handle id of a port: `<flow>:<dir>:<name>` (flow "data" or "ctrl", dir "in" or "out"). */
export const handleId = (flow, dir, name) => `${flow}:${dir}:${name}`

export function parseHandle(id) {
  const [flow, dir, ...rest] = id.split(":")
  return { flow, dir, name: rest.join(":") }
}

export const edgeKey = (e) => `${e.kind}|${e.from.node}|${e.from.port}|${e.to.node}|${e.to.port}`

export const flowOf = (e) => (e.kind === "ctrl" ? "ctrl" : "data")
export const sourceHandle = (e) => handleId(flowOf(e), "out", e.from.port)
export const targetHandle = (e) => handleId(flowOf(e), "in", e.to.port)

/** A control edge closing a loop: into a labelled merge past its entry, or into `next`. */
export function isBackEdge(e, byId) {
  if (e.kind !== "ctrl") return false
  const target = byId.get(e.to.node)
  if (target?.kind === "each" || target?.kind === "collect") return e.to.port === "next"
  if (target?.kind !== "merge" || !target.props?.label) return false
  return e.to.port !== "in_0"
}

/** The type a data edge carries: its source port's, else its target port's. */
export function edgeType(e, byId) {
  const src = (byId.get(e.from.node)?.outputs || []).find((p) => p.port === e.from.port)
  const dst = (byId.get(e.to.node)?.inputs || []).find((p) => p.port === e.to.port)
  return src?.type || dst?.type || null
}
