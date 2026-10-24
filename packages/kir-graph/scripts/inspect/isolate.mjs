/**
 * Lays out one graph of one example in one view under variants of the view,
 * reporting which variants ELK fails on:
 * node scripts/inspect/isolate.mjs <example id> <style> <graph> <view>
 */

import { readFileSync } from "node:fs"
import ELK from "elkjs/lib/elk.bundled.js"

import { graphModel } from "../../src/model/graph.js"
import { layoutView, planLayout } from "../../src/layout/build.js"
import { GRAPH_VIEWS } from "../../src/views.js"

const [id, style, graph, viewName] = process.argv.slice(2)
const doc = JSON.parse(readFileSync(new URL(`../../dev/examples/${id}.json`, import.meta.url)))
const model = graphModel(doc.graphs[style], graph)
const base = GRAPH_VIEWS[viewName]
const variants = {
  as_is: base,
  no_tail_labels: { ...base, tailLabel: undefined },
}
// The ELK input itself: dangling edge ends and empty compounds
const { input } = planLayout(model, base, {})
const ids = new Set()
const empty = []
const walk = (n) => {
  ids.add(n.id)
  for (const p of n.ports || []) ids.add(p.id)
  if (n.children && !n.children.length && n.id !== "root") empty.push(n.id)
  for (const c of n.children || []) walk(c)
}
walk(input)
const dangling = input.edges.filter((e) => ![...e.sources, ...e.targets].every((x) => ids.has(x)))
console.log(`input: ${ids.size} ids, empty compounds ${JSON.stringify(empty)}, dangling edges ${JSON.stringify(dangling.map((e) => e.id))}`)

// Which ELK step fails: rerun the same input with one strategy changed at every level
const elk = new ELK()
const STEPS = {
  placement_bk: { "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF" },
  layering_longest: { "elk.layered.layering.strategy": "LONGEST_PATH" },
  no_straight: { "elk.layered.nodePlacement.favorStraightEdges": "false" },
  compaction_none: { "elk.layered.compaction.postCompaction.strategy": "NONE" },
}
const withOptions = (n, extra) => ({
  ...n,
  layoutOptions: n.children ? { ...(n.layoutOptions || {}), ...extra } : n.layoutOptions,
  children: n.children?.map((c) => withOptions(c, extra)),
})
for (const [name, extra] of Object.entries(STEPS)) {
  try {
    await elk.layout(withOptions(structuredClone(input), extra))
    console.log(`ok   step ${name}`)
  } catch (e) {
    console.log(`FAIL step ${name} ${String(e?.message || e).slice(0, 100)}`)
  }
}

for (const [name, view] of Object.entries(variants))
  for (const regions of [true, false])
    for (const satellites of [true, false]) {
      try {
        const l = await layoutView(model, view, { regions, satellites })
        console.log(`ok   ${name} regions=${regions} satellites=${satellites} ${l.nodes.length}n ${l.columns ?? 1} columns`)
      } catch (e) {
        console.log(`FAIL ${name} regions=${regions} satellites=${satellites} ${String(e?.message || e).slice(0, 120)}`)
      }
    }
