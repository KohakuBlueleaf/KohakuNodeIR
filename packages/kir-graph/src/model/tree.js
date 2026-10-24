/**
 * A graph as a statement tree, read from its regions: the statements of a
 * region in order, each controller followed by the regions it owns. The block
 * and sequence views draw this tree.
 *
 * Items:
 * - `{t: "stmt", node}`: a call, an assignment, a graph's inputs or outputs;
 * - `{t: "group", node, arms: [{region, items}]}`: a branch, switch, parallel,
 *   each or collect with its bodies;
 * - `{t: "loop", node, region, items}`: a labelled merge (a jump target or an
 *   unentered namespace) with its body;
 * - `{t: "try", node, arms: [{region, items}, {region, items}]}`: body, handler;
 * - `{t: "dataflow", node, region, items}`;
 * - `{t: "jump", node, edge}`: a jump back to the loop of labelled merge `node`,
 *   last in the region it ends.
 */

import { EXPRESSIONS } from "./graph.js"

const GROUPS = new Set(["branch", "switch", "parallel", "each", "collect"])

/** Whether a node is a statement of the tree (not an expression or a plain join). */
export function isStatement(node) {
  if (EXPRESSIONS.has(node.kind) || node.kind === "dataflow") return false
  return node.kind !== "merge" || !!node.props?.label
}

/** A jump back into a loop: a control edge into a labelled merge past its entry. */
function isJumpBack(model, e) {
  if (e.kind !== "ctrl" || e.to.port === "in_0") return false
  const target = model.byId.get(e.to.node)
  return target?.kind === "merge" && !!target.props?.label
}

/** The jumps back that end a region: from one of its own statements, or straight from the port entering it. */
function jumpsOut(model, region) {
  const own = new Set(region.nodes)
  const entry = region.owner
  const entering = new Set([...model.regions.values()].filter((r) => r.owner).map((r) => `${r.owner.node}|${r.owner.port}`))
  const from = (e) => `${e.from.node}|${e.from.port}`
  return model.graph.edges
    .filter((e) => isJumpBack(model, e))
    .filter((e) => (own.has(e.from.node) && !entering.has(from(e))) || (entry && from(e) === `${entry.node}|${entry.port}`))
    .map((e) => ({ t: "jump", node: model.byId.get(e.to.node), edge: e }))
}

function arm(model, regionId) {
  const region = model.regions.get(regionId)
  return { region, items: [...items(model, region.nodes), ...jumpsOut(model, region)] }
}

function items(model, ids) {
  const out = []
  for (const id of ids) {
    const node = model.byId.get(id)
    const owned = model.owned.get(id) || []
    if (node.kind === "dataflow") {
      const region = owned[0]
      if (region) out.push({ t: "dataflow", node, ...arm(model, region) })
      continue
    }
    if (!isStatement(node)) continue
    if (GROUPS.has(node.kind)) out.push({ t: "group", node, arms: owned.map((r) => arm(model, r)) })
    else if (node.kind === "try") out.push({ t: "try", node, arms: owned.map((r) => arm(model, r)) })
    else if (node.kind === "merge") {
      const region = owned[0]
      out.push(region ? { t: "loop", node, ...arm(model, region) } : { t: "stmt", node })
    } else out.push({ t: "stmt", node })
  }
  return out
}

/** The statement tree of a graph's top level. */
export function statementTree(model) {
  const top = { nodes: model.rootNodes, owner: null }
  return [...items(model, model.rootNodes), ...jumpsOut(model, top)]
}

/** The item lists an item holds. */
export function itemSlots(it) {
  if (it.arms) return it.arms.map((a) => a.items)
  if (it.items) return [it.items]
  return []
}

/** The control edges that jump back into a labelled merge (past its entry). */
export function loopSources(model, mergeId) {
  return model.graph.edges.filter((e) => e.kind === "ctrl" && e.to.node === mergeId && e.to.port !== "in_0")
}
