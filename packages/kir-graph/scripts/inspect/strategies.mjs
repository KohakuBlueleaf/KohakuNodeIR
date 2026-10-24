/**
 * The drawn size of one graph in one view under every ELK layering and node
 * placement strategy, smallest area first, to choose them by measurement:
 * node scripts/inspect/strategies.mjs <example id> <graph> [view]
 */

import { readFileSync } from "node:fs"

import { graphModel } from "../../src/model/graph.js"
import { layoutView } from "../../src/layout/build.js"
import { checkLayout, layoutOk } from "../../src/layout/checks.js"
import { GRAPH_VIEWS, viewData } from "../../src/views.js"

const [id, graph, viewName = "flowchart"] = process.argv.slice(2)
const doc = JSON.parse(readFileSync(new URL(`../../dev/examples/${id}.json`, import.meta.url)))
const model = graphModel(doc.graphs[viewData(viewName)], graph)
const LAYERING = ["NETWORK_SIMPLEX", "LONGEST_PATH", "LONGEST_PATH_SOURCE", "COFFMAN_GRAHAM", "STRETCH_WIDTH", "MIN_WIDTH"]
const PLACEMENT = ["NETWORK_SIMPLEX", "BRANDES_KOEPF", "LINEAR_SEGMENTS", "SIMPLE"]
const rows = []
for (const layering of LAYERING)
  for (const placement of PLACEMENT) {
    try {
      const l = await layoutView(model, GRAPH_VIEWS[viewName], { layering, placement })
      const { w, h } = l.bounds
      rows.push({ layering, placement, w: Math.round(w), h: Math.round(h), area: Math.round((w * h) / 1000), ok: layoutOk(checkLayout(l)) })
    } catch (e) {
      rows.push({ layering, placement, error: String(e?.message || e).slice(0, 60) })
    }
  }
rows.sort((a, b) => (a.area ?? Infinity) - (b.area ?? Infinity))
for (const r of rows) console.log(r.error ? `${r.layering} / ${r.placement}: ${r.error}` : `${String(r.area).padStart(6)}k  ${r.w}x${r.h}  ${r.ok ? "ok  " : "BAD "} ${r.layering} / ${r.placement}`)
