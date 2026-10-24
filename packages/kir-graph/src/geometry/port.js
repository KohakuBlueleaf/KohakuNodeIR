/** A port as geometry places it: handle, side, position in the node's box, colour. */

import { handleId } from "../model/ports.js"
import { CTRL, typeColor } from "../model/types.js"

/** `p`: a port name or a node's port entry (`{port, type}`). */
export function makePort(flow, dir, p, x, y, side, extra = {}) {
  const name = typeof p === "string" ? p : p.port
  const type = flow === "data" && typeof p !== "string" ? p.type || null : null
  return {
    handle: handleId(flow, dir, name),
    name,
    flow,
    dir,
    side,
    x,
    y,
    type,
    color: flow === "data" ? typeColor(type) : CTRL,
    ...extra,
  }
}

/** `n` points evenly spread over `[from, to]`, centred in their slots. */
export function spread(n, from, to) {
  if (n <= 0) return []
  const step = (to - from) / n
  return Array.from({ length: n }, (_, i) => from + step * (i + 0.5))
}
