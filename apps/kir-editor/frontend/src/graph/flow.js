/**
 * One graph of a .kirgraph document plus a layout -> Vue Flow nodes and edges,
 * for any view style.
 *
 * A dataflow node is a group (Vue Flow parent) around its members, whose
 * positions are relative to it; frames-style regions are drawn behind
 * everything. An edge carries its ELK route together with the page positions
 * its two nodes had when the route was made, so it draws the route only
 * while neither node has moved.
 */

import { FRAME_PAD } from "@/graph/layout"
import { edgeKey, edgeType, handleId, isBackEdge, membership, sourceHandle, targetHandle } from "@/graph/ports"
import { CTRL_COLOR, typeColor } from "@/graph/types"

/** A group's box: ELK's, grown to hold its members wherever they now are. */
function groupBox(group, byId, layout, geometry, sides) {
  const elk = layout?.frames?.[group.id]
  let w = elk?.w ?? 160
  let h = elk?.h ?? 60
  for (const m of group.props?.members || []) {
    const node = byId.get(m)
    const pos = layout?.positions?.[m]
    if (!node || !pos) continue
    const g = geometry(node)
    w = Math.max(w, pos.x + g.w + FRAME_PAD.side)
    h = Math.max(h, pos.y + g.h + FRAME_PAD.bottom)
  }
  const ports = []
  const at = (dir, name) => elk?.ports?.[handleId("ctrl", dir, name)]
  for (const p of group.ctrl_in || []) {
    const e = at("in", p)
    ports.push(sides[0] === "NORTH" ? { handle: handleId("ctrl", "in", p), dir: "in", side: "top", x: e?.x ?? w / 2, y: 0 } : { handle: handleId("ctrl", "in", p), dir: "in", side: "left", x: 0, y: e?.y ?? 20 })
  }
  for (const p of group.ctrl_out || []) {
    const e = at("out", p)
    ports.push(sides[1] === "SOUTH" ? { handle: handleId("ctrl", "out", p), dir: "out", side: "bottom", x: e?.x ?? w / 2, y: h } : { handle: handleId("ctrl", "out", p), dir: "out", side: "right", x: w, y: e?.y ?? 20 })
  }
  return { w, h, ports: ports.map((p) => ({ ...p, flow: "ctrl", color: CTRL_COLOR })) }
}

/**
 * `opts`: `{geometry(node), nodeType, showCtrl, frameSides, hidden: Set, regions: [], selectedId, extra: {}}`;
 * `extra` is merged into every node's data (view-wide settings).
 */
export function toFlow(graph, layout, opts) {
  if (!graph) return { nodes: [], edges: [] }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const memberOf = membership(graph)
  const hidden = opts.hidden || new Set()
  const placed = (id) => layout?.positions?.[id] || { x: 0, y: 0 }
  const wired = new Map()
  for (const e of graph.edges)
    if (e.kind === "data") wired.set(e.to.node, [...(wired.get(e.to.node) || []), e.to.port])

  const nodes = []
  for (const r of opts.regions || []) {
    nodes.push({
      id: r.id,
      type: "region",
      position: { x: r.x, y: r.y },
      data: { region: r },
      style: { width: `${r.w}px`, height: `${r.h}px` },
      draggable: false,
      selectable: false,
      connectable: false,
      zIndex: -10 + r.depth,
    })
  }
  // Vue Flow needs a parent before its children.
  for (const n of graph.nodes) {
    if (n.kind !== "dataflow" || hidden.has(n.id)) continue
    const box = groupBox(n, byId, layout, opts.geometry, opts.frameSides || ["NORTH", "SOUTH"])
    nodes.push({
      id: n.id,
      type: "group",
      position: placed(n.id),
      data: { node: n, box, ...opts.extra },
      style: { width: `${box.w}px`, height: `${box.h}px` },
      selected: n.id === opts.selectedId,
      zIndex: -1,
    })
  }
  for (const n of graph.nodes) {
    if (n.kind === "dataflow" || hidden.has(n.id)) continue
    const parent = memberOf.get(n.id)
    nodes.push({
      id: n.id,
      type: opts.nodeType,
      position: placed(n.id),
      data: { node: n, geom: opts.geometry(n), wired: wired.get(n.id) || [], ...opts.extra },
      selected: n.id === opts.selectedId,
      ...(parent && byId.has(parent) && !hidden.has(parent) ? { parentNode: parent } : {}),
    })
  }

  const edges = []
  for (const e of graph.edges) {
    if (!byId.has(e.from.node) || !byId.has(e.to.node)) continue
    if (hidden.has(e.from.node) || hidden.has(e.to.node)) continue
    if (e.kind === "ctrl" && !opts.showCtrl) continue
    const key = edgeKey(e)
    const color = e.kind === "ctrl" ? opts.ctrlColor || CTRL_COLOR : opts.dataColor?.(edgeType(e, byId)) || typeColor(edgeType(e, byId))
    const route = layout?.routes?.[key]
    edges.push({
      id: key,
      type: "wire",
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
      ...(e.kind === "ctrl" && opts.arrows ? { markerEnd: { type: "arrowclosed", color, width: 16, height: 16 } } : {}),
    })
  }
  return { nodes, edges }
}
