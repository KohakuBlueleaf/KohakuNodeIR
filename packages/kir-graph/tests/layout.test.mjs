/**
 * Every example graph (scripts/generate/examples.py), in every graph view and data
 * style, with regions drawn, collapsed to the top level, and without regions:
 * the layout's geometry properties hold (src/layout/checks.js). Layout time
 * per graph is reported, not checked.
 */

import assert from "node:assert/strict"
import { readFileSync, existsSync } from "node:fs"
import { test } from "node:test"

import { graphModel } from "../src/model/graph.js"
import { layoutView } from "../src/layout/build.js"
import { checkLayout } from "../src/layout/checks.js"
import { GRAPH_VIEWS } from "../src/views.js"

const DIR = new URL("../dev/examples/", import.meta.url)
const index = existsSync(new URL("index.json", DIR)) ? JSON.parse(readFileSync(new URL("index.json", DIR))) : []
const report = []

const variants = (model) => [
  ["regions", {}],
  ["collapsed", { collapsed: model.roots }],
  ["flat", { regions: false }],
]

// With no examples generated nothing below would run, and the suite would pass on nothing
test("examples exist", () => assert.ok(index.some((e) => !e.error), "no examples: run scripts/generate/examples.py"))

for (const entry of index.filter((e) => !e.error)) {
  test(entry.id, async () => {
    const doc = JSON.parse(readFileSync(new URL(`${entry.id}.json`, DIR)))
    for (const [style, kirgraph] of Object.entries(doc.graphs))
      for (const g of kirgraph.graphs) {
        const model = graphModel(kirgraph, g.name)
        for (const [viewName, view] of Object.entries(GRAPH_VIEWS))
          for (const [variant, opts] of variants(model)) {
            const layout = await layoutView(model, view, opts)
            const where = `${style} ${g.name} ${viewName} ${variant}`
            const c = checkLayout(layout)
            for (const [prop, list] of Object.entries(c)) assert.deepEqual(list, [], `${where}: ${prop}`)
            report.push({ id: entry.id, where, nodes: layout.nodes.length, edges: layout.edges.length, ms: layout.ms })
          }
      }
  })
}

test("report", { skip: !index.length }, () => {
  const slow = [...report].sort((a, b) => b.ms - a.ms).slice(0, 8)
  for (const r of slow) console.log(`${r.ms.toFixed(0).padStart(6)} ms  ${r.nodes} nodes ${r.edges} edges  ${r.id} ${r.where}`)
})
