/**
 * Prints the data wires of one graph of one example in one data style, one
 * per line with both ends' kinds and variable names, to read how KIR resolved
 * variables: node scripts/inspect/dataflow.mjs <example id> <style> <graph>
 */

import { readFileSync } from "node:fs"

const [id, style, graph] = process.argv.slice(2)
const doc = JSON.parse(readFileSync(new URL(`../../dev/examples/${id}.json`, import.meta.url)))
const g = doc.graphs[style].graphs.find((x) => x.name === graph)
const byId = new Map(g.nodes.map((n) => [n.id, n]))
const show = (end) => {
  const n = byId.get(end.node)
  const name = n?.props?.name ? ` ${n.props.name}` : n?.name ? ` ${n.name}` : ""
  return `${end.node} (${n?.kind}${name}).${end.port}`
}
for (const n of g.nodes) if (n.kind !== "get" && n.kind !== "set" && n.kind !== "value") console.log(`node ${n.id} ${n.kind} ${n.name ?? ""} region=${n.region ?? "-"}`)
for (const e of g.edges) if (e.kind !== "ctrl") console.log(`${show(e.from)} -> ${show(e.to)}`)
