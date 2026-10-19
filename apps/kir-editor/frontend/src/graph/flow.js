/**
 * One graph of a .kirgraph document plus its layout -> Vue Flow nodes and edges.
 *
 * A dataflow node is a frame (Vue Flow parent) around its members, whose
 * positions are relative to it. An edge carries its ELK route together with
 * the page positions its two nodes had when the route was made, so the edge
 * draws the route only while neither node has moved.
 */

import {
  FRAME_PAD,
  edgeKey,
  isBackEdge,
  membership,
  sourceHandle,
  targetHandle,
} from "@/graph/layout"
import { framePorts, nodeGeometry } from "@/graph/geometry"
import { CTRL_COLOR, typeColor } from "@/graph/types"

function portType(node, list, port) {
  return (node?.[list] || []).find((p) => p.port === port)?.type || null
}

/** A frame's box: ELK's, grown to hold its members wherever they now are. */
function frameBox(frame, byId, layout, ctx) {
  const elk = layout?.frames?.[frame.id]
  let w = elk?.w ?? 160
  let h = elk?.h ?? 60
  for (const m of frame.props?.members || []) {
    const node = byId.get(m)
    const pos = layout?.positions?.[m]
    if (!node || !pos) continue
    const g = nodeGeometry(node, ctx)
    w = Math.max(w, pos.x + g.w + FRAME_PAD.side)
    h = Math.max(h, pos.y + g.h + FRAME_PAD.bottom)
  }
  const box = { w, h, ports: elk?.ports || {} }
  return { ...box, ports: framePorts(frame, box) }
}

export function toFlow(graph, layout, ctx, selectedId) {
  if (!graph) return { nodes: [], edges: [] }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const memberOf = membership(graph)
  const nodes = []
  const placed = (id) => layout?.positions?.[id] || { x: 0, y: 0 }
  // Vue Flow needs a parent before its children.
  for (const n of graph.nodes) {
    if (n.kind !== "dataflow") continue
    const box = frameBox(n, byId, layout, ctx)
    nodes.push({
      id: n.id,
      type: "frame",
      position: placed(n.id),
      data: { node: n, box },
      style: { width: `${box.w}px`, height: `${box.h}px` },
      selected: n.id === selectedId,
      zIndex: -1,
    })
  }
  for (const n of graph.nodes) {
    if (n.kind === "dataflow") continue
    const parent = memberOf.get(n.id)
    nodes.push({
      id: n.id,
      type: "kir",
      position: placed(n.id),
      data: { node: n, geom: nodeGeometry(n, ctx), isDefCall: ctx.defNames?.has(n.name) },
      selected: n.id === selectedId,
      ...(parent && byId.has(parent) ? { parentNode: parent } : {}),
    })
  }

  const edges = []
  for (const e of graph.edges) {
    if (!byId.has(e.from.node) || !byId.has(e.to.node)) continue
    const key = edgeKey(e)
    const color =
      e.kind === "ctrl"
        ? CTRL_COLOR
        : typeColor(
            portType(byId.get(e.from.node), "outputs", e.from.port) ||
              portType(byId.get(e.to.node), "inputs", e.to.port),
          )
    const route = layout?.routes?.[key]
    edges.push({
      id: key,
      type: "kir",
      source: e.from.node,
      target: e.to.node,
      sourceHandle: sourceHandle(e),
      targetHandle: targetHandle(e),
      data: {
        kind: e.kind,
        color,
        back: isBackEdge(e, byId),
        route: route || null,
        at: route ? { s: layout.absolute?.[e.from.node], t: layout.absolute?.[e.to.node] } : null,
      },
      ...(e.kind === "ctrl" ? { markerEnd: { type: "arrowclosed", color, width: 16, height: 16 } } : {}),
    })
  }
  return { nodes, edges }
}
