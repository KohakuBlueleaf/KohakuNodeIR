/**
 * Edits of one graph of a .kirgraph document (graph.md), in place. Every function keeps the graph
 * valid for `from_graph`: an input takes at most one edge, a control output
 * leads to one place, a merge's input ports are numbered without gaps.
 */

import { edgeKey, isStatement, parseHandle } from "@kohaku/kir-graph"

/** The free `in_<n>` slot a merge offers for one more incoming path. */
const mergeSlot = (node) => `in_${(node.ctrl_in || []).length}`

// ---------------------------------------------------------------- names

function usedNames(graph) {
  const out = new Set()
  for (const n of graph.nodes) {
    for (const p of n.outputs || []) if (p.var) out.add(p.var)
    for (const k of ["name", "item", "index", "error_name"]) if (n.props?.[k]) out.add(n.props[k])
  }
  for (const p of graph.params || []) out.add(p.name)
  return out
}

function usedLabels(graph) {
  const out = new Set()
  for (const n of graph.nodes) {
    const p = n.props || {}
    if (p.label) out.add(p.label)
    for (const v of Object.values(p.labels || {})) out.add(v)
  }
  return out
}

function fresh(used, base) {
  const clean = base.replace(/[^A-Za-z0-9_]/g, "_").replace(/__+/g, "_") || "x"
  let name = clean
  for (let i = 2; used.has(name); i++) name = `${clean}${i}`
  used.add(name)
  return name
}

export function uniqueId(graph, base) {
  const ids = new Set(graph.nodes.map((n) => n.id))
  const clean = base.replace(/\./g, "_")
  let i = graph.nodes.length + 1
  while (ids.has(`${clean}_${i}`)) i++
  return `${clean}_${i}`
}

// ---------------------------------------------------------------- new nodes

/**
 * A new node. `spec.kind` is a node kind; a call also gives `name` (as the
 * text will write it) and `sig` (its signature in kirsig form).
 */
export function makeNode(graph, spec) {
  const names = usedNames(graph)
  const labels = usedLabels(graph)
  const base = { id: uniqueId(graph, spec.kind === "call" ? spec.name : spec.kind), kind: spec.kind }
  switch (spec.kind) {
    case "call": {
      // Inputs after the first optional one are keywords, so skipping one never shifts the rest.
      let keyword = false
      const inputs = (spec.sig?.inputs || []).map((p) => {
        keyword ||= "default" in p
        return { port: p.name, ...(p.type ? { type: p.type } : {}), ...(keyword ? { keyword: true } : {}) }
      })
      const outputs = (spec.sig?.outputs || []).map((p) => ({
        port: p.name,
        var: fresh(names, p.name),
        ...(p.type ? { type: p.type } : {}),
      }))
      return { ...base, name: spec.name, inputs, outputs, ctrl_in: ["in"], ctrl_out: ["out"] }
    }
    case "assign":
      return {
        ...base,
        inputs: [{ port: "value", value: 0 }],
        outputs: [{ port: "value", var: fresh(names, spec.name || "x") }],
        ctrl_in: ["in"],
        ctrl_out: ["out"],
      }
    case "value":
      return { ...base, props: { value: spec.value ?? 0 }, outputs: [{ port: "value" }] }
    case "get":
      return {
        ...base,
        props: { name: spec.name || [...names][0] || "x" },
        outputs: [{ port: "value" }],
      }
    case "set":
      return { ...base, props: { name: spec.name || fresh(names, "x") }, inputs: [{ port: "value" }] }
    case "branch":
      return {
        ...base,
        props: { labels: { true: fresh(labels, "yes"), false: fresh(labels, "no") } },
        inputs: [{ port: "cond" }],
        ctrl_in: ["in"],
        ctrl_out: ["true", "false"],
      }
    case "switch":
      return {
        ...base,
        props: {
          cases: [0, 1],
          labels: {
            case_0: fresh(labels, "case0"),
            case_1: fresh(labels, "case1"),
            default: fresh(labels, "other"),
          },
        },
        inputs: [{ port: "value" }],
        ctrl_in: ["in"],
        ctrl_out: ["case_0", "case_1", "default"],
      }
    case "merge":
      return { ...base, ctrl_in: [], ctrl_out: ["out"] }
    case "each":
    case "collect": {
      const collecting = spec.kind === "collect"
      const item = fresh(names, "item")
      const index = fresh(names, "i")
      const target = collecting ? fresh(names, "results") : null
      return {
        ...base,
        props: { label: fresh(labels, "body"), item, index, has_index: true, ...(collecting ? { target } : {}) },
        inputs: [{ port: "items" }, ...(collecting ? [{ port: "value", deferred: "body_end", value: null }] : [])],
        outputs: [
          { port: "item", var: item },
          { port: "index", var: index },
          ...(collecting ? [{ port: "results", var: target }] : []),
        ],
        ctrl_in: ["in", "next"],
        ctrl_out: ["body", "done"],
      }
    }
    case "parallel":
      return {
        ...base,
        props: { labels: { out_0: fresh(labels, "left"), out_1: fresh(labels, "right") } },
        ctrl_in: ["in"],
        ctrl_out: ["out_0", "out_1"],
      }
    case "try": {
      const err = fresh(names, "err")
      return {
        ...base,
        props: { error_name: err },
        outputs: [{ port: "error", var: err }],
        ctrl_in: ["in"],
        ctrl_out: ["try", "except"],
      }
    }
    default:
      throw new Error(`cannot create a ${spec.kind} node`)
  }
}

// ---------------------------------------------------------------- edges

/** Whether a drag from one handle to another can become an edge. */
export function isValidConnection(c, graph = null) {
  if (!c.sourceHandle || !c.targetHandle) return false
  const s = parseHandle(c.sourceHandle)
  const t = parseHandle(c.targetHandle)
  if (s.dir !== "out" || t.dir !== "in" || s.flow !== t.flow) return false
  if (c.source !== c.target) return true
  const node = graph?.nodes.find((n) => n.id === c.target)
  // The loop binding exists before body-end capture. No other self dependency
  // is valid: in particular results cannot feed their own unfinished collection.
  return node?.kind === "collect" && s.flow === "data" && ["item", "index"].includes(s.name)
    && (s.name !== "index" || node.props?.has_index)
    && node.outputs?.some((p) => p.port === s.name && p.var)
    && t.name === "value" && node.inputs?.some((p) => p.port === "value" && p.deferred === "body_end")
}

/** Add the edge a connection describes; returns false when it is not valid. */
export function connect(graph, c) {
  if (!isValidConnection(c, graph)) return false
  const s = parseHandle(c.sourceHandle)
  const t = parseHandle(c.targetHandle)
  const target = graph.nodes.find((n) => n.id === c.target)
  if (!target) return false
  if (s.flow === "data") {
    graph.edges = graph.edges.filter(
      (e) => !(e.kind === "data" && e.to.node === c.target && e.to.port === t.name),
    )
    const port = (target.inputs || []).find((p) => p.port === t.name)
    if (port) delete port.value
    // One output names at most one variable: wiring it into a set replaces its other set.
    if (target.kind === "set") {
      const isSet = (id) => graph.nodes.find((n) => n.id === id)?.kind === "set"
      graph.edges = graph.edges.filter(
        (e) =>
          !(e.kind === "data" && e.from.node === c.source && e.from.port === s.name && isSet(e.to.node)),
      )
    }
  } else {
    graph.edges = graph.edges.filter(
      (e) => !(e.kind === "ctrl" && e.from.node === c.source && e.from.port === s.name),
    )
    if (target.kind === "merge" && t.name === mergeSlot(target)) target.ctrl_in.push(t.name)
  }
  graph.edges.push({
    kind: s.flow === "data" ? "data" : "ctrl",
    from: { node: c.source, port: s.name },
    to: { node: c.target, port: t.name },
  })
  return true
}

/** Renumber each merge's inputs in_0.. over the ports that still carry an edge. */
export function compactMerges(graph) {
  for (const m of graph.nodes) {
    if (m.kind !== "merge") continue
    const live = m.ctrl_in.filter((p) =>
      graph.edges.some((e) => e.kind === "ctrl" && e.to.node === m.id && e.to.port === p),
    )
    const rename = new Map(live.map((p, i) => [p, `in_${i}`]))
    for (const e of graph.edges)
      if (e.kind === "ctrl" && e.to.node === m.id && rename.has(e.to.port))
        e.to.port = rename.get(e.to.port)
    m.ctrl_in = live.map((_, i) => `in_${i}`)
  }
}

export function removeEdges(graph, keys) {
  const drop = new Set(keys)
  graph.edges = graph.edges.filter((e) => !drop.has(edgeKey(e)))
  compactMerges(graph)
}

/** Remove nodes with their edges; returns the members of removed dataflow frames. */
export function removeNodes(graph, ids) {
  const drop = new Set(ids)
  const orphans = []
  for (const n of graph.nodes)
    if (n.kind === "dataflow" && drop.has(n.id))
      orphans.push(...(n.props?.members || []).filter((m) => !drop.has(m)))
  graph.nodes = graph.nodes.filter((n) => !drop.has(n.id))
  for (const n of graph.nodes)
    if (n.kind === "dataflow") n.props.members = n.props.members.filter((m) => !drop.has(m))
  graph.edges = graph.edges.filter((e) => !drop.has(e.from.node) && !drop.has(e.to.node))
  compactMerges(graph)
  return orphans
}

// ---------------------------------------------------------------- arms of switch / parallel

export function addArm(graph, node) {
  const labels = usedLabels(graph)
  if (node.kind === "parallel") {
    const port = `out_${node.ctrl_out.length}`
    node.ctrl_out.push(port)
    node.props.labels[port] = fresh(labels, "arm")
  } else if (node.kind === "switch") {
    const i = node.props.cases.length
    const port = `case_${i}`
    node.props.cases.push(i)
    node.props.labels[port] = fresh(labels, `case${i}`)
    const at = node.ctrl_out.indexOf("default")
    node.ctrl_out.splice(at < 0 ? node.ctrl_out.length : at, 0, port)
  }
}

export function removeArm(graph, node) {
  let port = null
  if (node.kind === "parallel" && node.ctrl_out.length > 1) port = node.ctrl_out.at(-1)
  if (node.kind === "switch" && node.props.cases.length > 1) {
    port = `case_${node.props.cases.length - 1}`
    node.props.cases.pop()
  }
  if (!port) return
  node.ctrl_out = node.ctrl_out.filter((p) => p !== port)
  delete node.props.labels[port]
  graph.edges = graph.edges.filter(
    (e) => !(e.kind === "ctrl" && e.from.node === node.id && e.from.port === port),
  )
}

/** Give a switch a default arm, or take it away. */
export function toggleDefault(graph, node) {
  if (node.ctrl_out.includes("default")) {
    node.ctrl_out = node.ctrl_out.filter((p) => p !== "default")
    delete node.props.labels.default
    graph.edges = graph.edges.filter(
      (e) => !(e.kind === "ctrl" && e.from.node === node.id && e.from.port === "default"),
    )
  } else {
    node.ctrl_out.push("default")
    node.props.labels.default = fresh(usedLabels(graph), "other")
  }
}

/**
 * The id of the last statement of `region` (a region id; null: the graph's
 * top level) that control leaves through `out`, in program order; null when
 * it has none.
 */
export function lastStatement(graph, region) {
  const inside = graph.nodes.filter((n) => (n.region ?? null) === region && isStatement(n) && (n.ctrl_out || []).includes("out"))
  return inside.at(-1)?.id ?? null
}

/**
 * Put `node` on the control chain right after `afterId`: the edge leaving
 * `afterId` now leaves `node`. A node without an `out` port (a branch) or a
 * missing one leaves the graph as it is.
 */
export function insertAfter(graph, afterId, node) {
  const after = graph.nodes.find((n) => n.id === afterId)
  if (!after || !(after.ctrl_out || []).includes("out")) return
  const next = graph.edges.find((e) => e.kind === "ctrl" && e.from.node === afterId && e.from.port === "out")
  if (next) next.from = { node: node.id, port: "out" }
  graph.edges.push({ kind: "ctrl", from: { node: afterId, port: "out" }, to: { node: node.id, port: "in" } })
}

// ---------------------------------------------------------------- to the backend

const CHAINABLE = new Set(["call", "assign"])

/**
 * The graph as `from_graph` reads it. A call or assign node that no control
 * edge touches belongs to the dataflow part of the canvas, so its unused
 * control ports are left out.
 */
export function serializeGraph(graph) {
  const touched = new Set()
  for (const e of graph.edges) if (e.kind === "ctrl") touched.add(e.from.node).add(e.to.node)
  const out = JSON.parse(JSON.stringify(graph))
  for (const n of out.nodes) {
    if (CHAINABLE.has(n.kind) && !touched.has(n.id)) {
      n.ctrl_in = []
      n.ctrl_out = []
    }
  }
  return out
}
