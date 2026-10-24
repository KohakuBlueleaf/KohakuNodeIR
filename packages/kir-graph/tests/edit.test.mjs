/**
 * Editing layouts (src/layout/place.js) over the example graphs, in the views
 * an editor draws (nodes, flowchart), both data styles:
 *
 * - a fresh editable layout keeps every geometry property (src/layout/checks.js);
 * - drawing the same graph again from memory moves nothing, reroutes nothing
 *   and runs no ELK;
 * - moving an element moves only it: every wire at it is rerouted to end on
 *   its pins with only horizontal and vertical runs, every other wire keeps
 *   its route, and every region box still holds what it holds;
 * - adding a statement where the host placed it, or removing one, leaves
 *   every other element where it was.
 */

import assert from "node:assert/strict"
import { existsSync, readFileSync } from "node:fs"
import { test } from "node:test"

import { layoutView } from "../src/layout/build.js"
import { checkLayout } from "../src/layout/checks.js"
import { createMemory, keepLayout, placeLayout, remember } from "../src/layout/place.js"
import { graphModel } from "../src/model/graph.js"
import { GRAPH_VIEWS } from "../src/views.js"

const DIR = new URL("../dev/examples/", import.meta.url)
const index = existsSync(new URL("index.json", DIR)) ? JSON.parse(readFileSync(new URL("index.json", DIR))) : []
const VIEWS = ["nodes", "flowchart"]
const LIMIT = 300
const MOVE = { x: 137, y: 61 }

test("examples exist", () => assert.ok(index.some((e) => !e.error), "no examples: run scripts/generate/examples.py"))

const near = (a, b) => Math.abs(a.x - b.x) < 0.01 && Math.abs(a.y - b.y) < 0.01
const positions = (l) => new Map(l.nodes.map((n) => [n.id, { x: n.x, y: n.y }]))
const routes = (l) => new Map(l.edges.map((e) => [e.id, JSON.stringify(e.route)]))

/** Where a wire must end: the drawn pin of the element it leaves or enters. */
function pin(layout, id, handle) {
  const n = layout.nodes.find((x) => x.id === id)
  if (n) {
    const p = n.geom.ports.find((q) => q.handle === handle)
    return p && { x: n.x + p.x, y: n.y + p.y }
  }
  const r = layout.regions.find((x) => x.id === id)
  const p = r?.ports?.[handle]
  return p && { x: r.x + p.x, y: r.y + p.y }
}

function orthogonal(route) {
  for (let i = 1; i < route.length; i++) {
    const [a, b] = [route[i - 1], route[i]]
    if (Math.abs(a.x - b.x) > 0.01 && Math.abs(a.y - b.y) > 0.01) return false
  }
  return true
}

function regionsHold(layout) {
  const bad = []
  const boxes = new Map([...layout.nodes, ...layout.regions].map((b) => [b.id, b]))
  for (const b of boxes.values()) {
    const r = b.parent && boxes.get(b.parent)
    if (r && !(r.x <= b.x + 0.01 && r.y <= b.y + 0.01 && r.x + r.w >= b.x + b.w - 0.01 && r.y + r.h >= b.y + b.h - 0.01)) bad.push(`${r.id} ⊅ ${b.id}`)
  }
  return bad
}

/** The graph with one more literal feeding nothing, and the graph without its last statement. */
function edits(kirgraph, name) {
  const g = kirgraph.graphs.find((x) => x.name === name)
  const added = { ...kirgraph, graphs: kirgraph.graphs.map((x) => (x === g ? { ...g, nodes: [...g.nodes, { id: "t_added", kind: "value", props: { value: 7 }, outputs: [{ port: "value" }] }] } : x)) }
  const last = [...g.nodes].reverse().find((n) => n.kind === "call")
  const removed = last && {
    ...kirgraph,
    graphs: kirgraph.graphs.map((x) => (x === g ? { ...g, nodes: g.nodes.filter((n) => n !== last), edges: g.edges.filter((e) => e.from.node !== last.id && e.to.node !== last.id) } : x)),
  }
  return { added, removed, last }
}

for (const entry of index.filter((e) => !e.error)) {
  test(entry.id, async () => {
    const doc = JSON.parse(readFileSync(new URL(`${entry.id}.json`, DIR)))
    for (const [style, kirgraph] of Object.entries(doc.graphs))
      for (const g of kirgraph.graphs) {
        if (g.nodes.length > LIMIT) continue
        const model = graphModel(kirgraph, g.name)
        for (const viewName of VIEWS) {
          const view = GRAPH_VIEWS[viewName]
          const where = `${style} ${g.name} ${viewName}`
          const opts = { editable: true }
          const fresh = await layoutView(model, view, opts)
          for (const [prop, list] of Object.entries(checkLayout(fresh))) assert.deepEqual(list, [], `${where} fresh: ${prop}`)

          const memory = createMemory()
          remember(memory, fresh)
          const again = await keepLayout(model, view, opts, memory)
          assert.equal(again.ms, 0, `${where}: ELK ran for an unchanged graph`)
          assert.deepEqual(positions(again), positions(fresh), `${where}: an unchanged graph moved`)
          assert.deepEqual(routes(again), routes(fresh), `${where}: an unchanged graph was rerouted`)

          const target = fresh.nodes.find((n) => n.node && model.byId.has(n.id))
          if (!target) continue
          memory.placed.set(target.id, { x: target.x + MOVE.x, y: target.y + MOVE.y })
          const moved = placeLayout(fresh.plan, memory)
          const before = routes(fresh)
          for (const n of moved.nodes) {
            const was = fresh.nodes.find((x) => x.id === n.id)
            const want = n.id === target.id ? { x: was.x + MOVE.x, y: was.y + MOVE.y } : was
            assert.ok(near(n, want), `${where}: moving ${target.id} moved ${n.id}`)
          }
          for (const e of moved.edges) {
            if (!e.route) continue
            const touches = e.source === target.id || e.target === target.id
            if (!touches) {
              assert.equal(JSON.stringify(e.route), before.get(e.id), `${where}: ${e.id} rerouted though neither end moved`)
              continue
            }
            assert.ok(orthogonal(e.route), `${where}: ${e.id} has a slanted run after the move`)
            const a = pin(moved, e.source, e.sourceHandle)
            const b = pin(moved, e.target, e.targetHandle)
            assert.ok(a && near(e.route[0], a), `${where}: ${e.id} does not leave its source pin`)
            assert.ok(b && near(e.route[e.route.length - 1], b), `${where}: ${e.id} does not enter its target pin`)
          }
          assert.deepEqual(regionsHold(moved), [], `${where}: a region box lost a member`)

          const { added, removed, last } = edits(kirgraph, g.name)
          const keepAll = (l, ref, skip) => {
            for (const n of l.nodes) {
              if (skip.has(n.id)) continue
              const was = ref.get(n.id)
              if (was) assert.ok(near(n, was), `${where}: an edit moved ${n.id}`)
            }
          }
          const ref = positions(moved)
          memory.placed.set("t_added", { x: -500, y: -500 })
          const withNew = await keepLayout(graphModel(added, g.name), view, opts, memory)
          assert.ok(near(withNew.nodes.find((n) => n.id === "t_added"), { x: -500, y: -500 }), `${where}: the added statement is not where it was placed`)
          keepAll(withNew, ref, new Set(["t_added"]))
          if (removed) {
            const without = await keepLayout(graphModel(removed, g.name), view, opts, memory)
            assert.ok(!without.nodes.some((n) => n.id === last.id), `${where}: the removed statement is still drawn`)
            keepAll(without, ref, new Set())
          }
        }
      }
  })
}
