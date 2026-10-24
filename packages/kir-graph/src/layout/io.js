/**
 * A graph's own inputs and outputs as the control-flow views draw them. The
 * `inputs` node becomes the Start terminal (Entry for a `@def`) and `outputs`
 * the End terminal (Exit), neither with data; every way out that leads
 * nowhere goes to the end, through a merge when there are several. Every
 * wire from `inputs` starts at an INPUT flag
 * of its own (`param: "input"`) and every wire into `outputs` ends at an
 * OUTPUT flag (`param: "output"`), so each sits beside the element it serves.
 * A `join` (KIR's flow style: the writes that reach a read) labels each input
 * with what feeds it.
 */

/** What a data wire comes from, in words: an input's name, else the producer and its port. */
function sourceLabel(node, port) {
  if (!node) return port
  if (node.kind === "inputs") return `input ${port}`
  if (node.kind === "call") return `${node.name}.${port}`
  if (node.kind === "assign") {
    const input = node.inputs?.[0]
    return input && "value" in input ? `= ${JSON.stringify(input.value)}` : "assign"
  }
  if (node.kind === "join") return `join ${node.props?.name}`
  return `${node.kind}.${port}`
}

export function withGraphIO(nodes, edges, main) {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const ins = nodes.find((n) => n.kind === "inputs")
  const outs = nodes.find((n) => n.kind === "outputs")
  const startId = ins?.id ?? "__start"
  const endId = outs?.id ?? "__end"
  const added = []
  const flowEdges = []
  const joinLabels = new Map()

  for (const e of edges) {
    if (e.kind !== "ctrl" && byId.get(e.to.node)?.kind === "join")
      joinLabels.set(`${e.to.node}|${e.to.port}`, sourceLabel(byId.get(e.from.node), e.from.port))
    if (e.kind !== "ctrl" && e.from.node === startId) {
      // A flag sits in the region of the element it serves, beside it
      const id = `param:in:${e.from.port}:${e.to.node}:${e.to.port}`
      const region = byId.get(e.to.node)?.region
      added.push({ id, kind: "get", param: "input", region, props: { name: e.from.port }, outputs: [{ port: "value" }] })
      flowEdges.push({ kind: e.kind, from: { node: id, port: "value" }, to: e.to })
    } else if (e.kind !== "ctrl" && e.to.node === endId) {
      const id = `param:out:${e.to.port}`
      const region = byId.get(e.from.node)?.region
      added.push({ id, kind: "set", param: "output", region, props: { name: e.to.port }, inputs: [{ port: "value" }] })
      flowEdges.push({ kind: e.kind, from: e.from, to: { node: id, port: "value" } })
    } else flowEdges.push(e)
  }

  const [startLabel, endLabel] = main ? ["Start", "End"] : ["Entry", "Exit"]
  const start = { id: startId, kind: "start", label: startLabel, ctrl_out: ["out"] }
  const end = { id: endId, kind: "end", label: endLabel, ctrl_in: ["in"] }
  const body = nodes
    .filter((n) => n !== ins && n !== outs)
    .map((n) =>
      n.kind === "join"
        ? {
            ...n,
            inputs: n.inputs.map((p) => ({ ...p, label: joinLabels.get(`${n.id}|${p.port}`) ?? p.port })),
            outputs: n.outputs.map((p) => ({ ...p, var: n.props?.name })),
          }
        : n,
    )

  // Control: into the first statement when there was no `inputs`; every way out that leads nowhere to the end
  const ctrl = flowEdges.filter((e) => e.kind === "ctrl")
  if (!ins) {
    const entered = new Set(ctrl.map((e) => e.to.node))
    const first = body.find((n) => !n.region && (n.ctrl_in || []).includes("in") && !entered.has(n.id))
    if (first) flowEdges.push({ kind: "ctrl", from: { node: startId, port: "out" }, to: { node: first.id, port: "in" } })
  }
  const leaving = new Set(ctrl.map((e) => `${e.from.node}|${e.from.port}`))
  for (const n of body)
    for (const p of n.ctrl_out || []) if (!leaving.has(`${n.id}|${p}`)) flowEdges.push({ kind: "ctrl", from: { node: n.id, port: p }, to: { node: endId, port: "in" } })
  // Several ways reaching the end join at a merge first, as arms joining anywhere else do
  const ending = flowEdges.filter((e) => e.kind === "ctrl" && e.to.node === endId)
  if (ending.length > 1) {
    const merge = { id: "__end_merge", kind: "merge", ctrl_in: ending.map((_, i) => `in_${i}`), ctrl_out: ["out"] }
    ending.forEach((e, i) => (e.to = { node: merge.id, port: `in_${i}` }))
    flowEdges.push({ kind: "ctrl", from: { node: merge.id, port: "out" }, to: { node: endId, port: "in" } })
    added.push(merge)
  }
  return { nodes: [start, ...body, ...added, end], edges: flowEdges }
}
