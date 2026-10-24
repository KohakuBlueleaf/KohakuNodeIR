/**
 * The installed package as an app uses it: run from a project that installed
 * the packed tarball and the peer dependencies (copied there first, so
 * `@kohaku/kir-graph` resolves to node_modules, not to this checkout), it
 * lays out every graph of one `.kirgraph` document in every graph view and
 * checks the layout's geometry: node tests/consumer.mjs <example json>
 */

import { readFileSync } from "node:fs"

import { GRAPH_VIEWS, checkLayout, graphModel, layoutOk, layoutView, viewData } from "@kohaku/kir-graph"

const doc = JSON.parse(readFileSync(process.argv[2], "utf-8"))
let failed = 0
for (const view of Object.keys(GRAPH_VIEWS)) {
  const kirgraph = doc.graphs[viewData(view)]
  for (const g of kirgraph.graphs) {
    const layout = await layoutView(graphModel(kirgraph, g.name), GRAPH_VIEWS[view])
    const ok = layoutOk(checkLayout(layout)) && layout.nodes.length > 0
    if (!ok) failed++
    console.log(`${ok ? "ok  " : "FAIL"} ${view} ${g.name}: ${layout.nodes.length} nodes, ${layout.edges.length} edges`)
  }
}
process.exit(failed ? 1 : 0)
