/**
 * The graph views: how each draws nodes, which way it lays them out and what
 * it does with control. `ctrl` is "draw" (control wires shown), "layout"
 * (control orders the layout but is not drawn: statements run down their
 * region boxes) or "none" (data only). `tailLabel(node, port)` names the wire
 * leaving a port, placed by the layout next to where it leaves. `regions:
 * false` never boxes regions: the view's own elements carry the structure.
 * `data` is the KIR data style a view draws (`to_graph(data=...)`).
 */

import { cardGeometry } from "./geometry/card.js"
import { roboGeometry, tailLabel } from "./geometry/robo.js"

export const GRAPH_VIEWS = {
  nodes: {
    label: "Nodes",
    nodeType: "card",
    direction: "DOWN",
    ctrl: "draw",
    regions: false,
    terminals: true,
    data: "wires",
    geometry: (n, ctx) => cardGeometry(n, { ...ctx, exec: true }),
  },
  frames: {
    label: "Frames",
    nodeType: "card",
    direction: "DOWN",
    ctrl: "layout",
    hideMerges: true,
    geometry: (n, ctx) => cardGeometry(n, { ...ctx, exec: false }),
  },
  dataflow: {
    label: "Dataflow",
    nodeType: "card",
    direction: "RIGHT",
    ctrl: "none",
    hideMerges: true,
    geometry: (n, ctx) => cardGeometry(n, { ...ctx, exec: false }),
  },
  flowchart: {
    label: "Flowchart",
    nodeType: "robo",
    direction: "DOWN",
    ctrl: "draw",
    arrows: true,
    terminals: true,
    palette: "robo",
    regions: false,
    data: "variables",
    tailLabel,
    geometry: (n, ctx) => roboGeometry(n, ctx),
  },
}

export const STATEMENT_VIEWS = {
  blocks: { label: "Blocks", data: "variables" },
  sequence: { label: "Sequence", data: "variables" },
}

/** The KIR data style view `name` draws. */
export const viewData = (name) => (GRAPH_VIEWS[name] || STATEMENT_VIEWS[name])?.data ?? "wires"

export const VIEW_NAMES = [...Object.keys(GRAPH_VIEWS), ...Object.keys(STATEMENT_VIEWS)]
