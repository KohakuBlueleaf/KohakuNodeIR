/**
 * One graph of a `.kirgraph` document as the views read it: nodes by id, the
 * region tree (version 3), what each node owns, and the data flowing into and
 * out of every port.
 */

import { edgeKey } from "./ports.js"

export const FORMATS = [2, 3]

/** Node kinds that are expressions of a statement rather than statements. */
export const EXPRESSIONS = new Set(["get", "set", "value"])

export function checkDocument(doc) {
  if (!doc || !FORMATS.includes(doc.kirgraph) || !Array.isArray(doc.graphs))
    throw new Error(`not a kirgraph document of version ${FORMATS.join(" or ")}`)
}

/** The overlay key of a node: its statement path when it has one, else its id. */
export const nodeKey = (n) => n.path ?? n.id

/**
 * The model of graph `name` of `doc`. `regions` maps region id to
 * `{...region, depth, regions: [child ids], nodes: [node ids in order]}`;
 * `roots` / `rootNodes` hold the top level.
 */
export function graphModel(doc, name = "main") {
  checkDocument(doc)
  const graph = doc.graphs.find((g) => g.name === name)
  if (!graph) throw new Error(`no graph named ${name}`)
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const regions = new Map()
  for (const r of graph.regions || []) {
    const parent = r.parent ? regions.get(r.parent) : null
    regions.set(r.id, { ...r, depth: parent ? parent.depth + 1 : 0, regions: [], nodes: [] })
    parent?.regions.push(r.id)
  }
  const roots = [...regions.values()].filter((r) => !r.parent).map((r) => r.id)
  const rootNodes = []
  for (const n of graph.nodes) (n.region ? regions.get(n.region).nodes : rootNodes).push(n.id)

  const owned = new Map()
  for (const r of regions.values()) {
    const owner = r.owner?.node
    if (owner) owned.set(owner, [...(owned.get(owner) || []), r.id])
  }

  const dataIn = new Map()
  const dataOut = new Map()
  for (const e of graph.edges) {
    if (e.kind !== "data") continue
    dataIn.set(`${e.to.node}|${e.to.port}`, e)
    const k = `${e.from.node}|${e.from.port}`
    dataOut.set(k, [...(dataOut.get(k) || []), e])
  }

  const defNames = new Set(doc.graphs.filter((g) => g.name !== "main").map((g) => g.name))
  return {
    doc,
    name,
    graph,
    byId,
    regions,
    roots,
    rootNodes,
    owned,
    dataIn,
    dataOut,
    defNames,
    edgeKeys: graph.edges.map(edgeKey),
  }
}

/** Ancestor region ids of a region, innermost first, itself included. */
export function regionChain(model, id) {
  const out = []
  for (let r = model.regions.get(id); r; r = r.parent ? model.regions.get(r.parent) : null) out.push(r.id)
  return out
}

/** Every node id inside a region, nested regions included. */
export function regionNodes(model, id) {
  const r = model.regions.get(id)
  if (!r) return []
  return [...r.nodes, ...r.regions.flatMap((c) => regionNodes(model, c))]
}

/**
 * What an input port reads, as an expression: `{lit}` (a literal box or a value
 * node), `{name}` (a variable, a parameter or a named output), `{wire, from}` (an
 * unnamed output of another node) or `{missing: true}`.
 */
export function inputExpr(model, node, port) {
  const entry = (node.inputs || []).find((p) => p.port === port)
  if (entry && "value" in entry) return { lit: entry.value }
  const e = model.dataIn.get(`${node.id}|${port}`)
  if (!e) return { missing: true }
  const src = model.byId.get(e.from.node)
  if (!src) return { missing: true }
  switch (src.kind) {
    case "get":
      return { name: src.props?.name ?? "?" }
    case "value":
      return { lit: src.props?.value }
    case "inputs":
      return { name: e.from.port }
  }
  const out = (src.outputs || []).find((p) => p.port === e.from.port)
  if (out?.var) return { name: out.var, from: src.id }
  return { wire: `${src.id}.${e.from.port}`, from: src.id }
}

/** The name each output port of a node binds (`null` for a discarded `_`). */
export function outputNames(model, node) {
  return (node.outputs || []).map((p) => {
    if ("var" in p) return p.var
    const set = (model.dataOut.get(`${node.id}|${p.port}`) || [])
      .map((e) => model.byId.get(e.to.node))
      .find((n) => n?.kind === "set")
    return set ? (set.props?.name ?? null) : null
  })
}
