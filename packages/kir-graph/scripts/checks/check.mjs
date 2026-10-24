/**
 * Lay out example graphs and print each layout's geometry violations and time:
 * node scripts/checks/check.mjs [id substring ...] [--views nodes,flowchart] [--quiet]
 */

import { readFileSync } from "node:fs"

import { graphModel } from "../../src/model/graph.js"
import { layoutView } from "../../src/layout/build.js"
import { checkLayout } from "../../src/layout/checks.js"
import { GRAPH_VIEWS } from "../../src/views.js"

const DIR = new URL("../../dev/examples/", import.meta.url)
const args = process.argv.slice(2)
const flag = (name) => {
  const i = args.indexOf(name)
  return i >= 0 ? args.splice(i, 2)[1] : null
}
const views = (flag("--views") || Object.keys(GRAPH_VIEWS).join(",")).split(",")
const quiet = args.includes("--quiet")
const filters = args.filter((a) => !a.startsWith("--"))
const index = JSON.parse(readFileSync(new URL("index.json", DIR)))
const chosen = index.filter((e) => !e.error && (!filters.length || filters.some((f) => e.id.includes(f))))

let bad = 0
for (const entry of chosen) {
  const doc = JSON.parse(readFileSync(new URL(`${entry.id}.json`, DIR)))
  for (const [style, kirgraph] of Object.entries(doc.graphs))
    for (const g of kirgraph.graphs) {
      const model = graphModel(kirgraph, g.name)
      for (const v of views)
        for (const [variant, opts] of [
          ["regions", {}],
          ["collapsed", { collapsed: model.roots }],
          ["flat", { regions: false }],
        ]) {
          const layout = await layoutView(model, GRAPH_VIEWS[v], opts)
          const c = checkLayout(layout)
          const problems = Object.entries(c).filter(([, l]) => l.length)
          if (problems.length) bad++
          if (problems.length || !quiet)
            console.log(
              `${problems.length ? "FAIL" : "ok  "} ${layout.ms.toFixed(0).padStart(6)}ms ${String(layout.nodes.length).padStart(5)}n ${entry.id} ${style} ${g.name} ${v} ${variant}` +
                problems.map(([k, l]) => `\n       ${k}: ${l.length} e.g. ${JSON.stringify(l.slice(0, 3))}`).join(""),
            )
        }
    }
}
console.log(`${bad} failing layouts`)
process.exit(bad ? 1 : 0)
