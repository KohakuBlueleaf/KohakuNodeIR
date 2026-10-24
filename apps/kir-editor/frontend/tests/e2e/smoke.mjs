/**
 * Browser smoke test of the editor: `npm run test:e2e`.
 *
 * Starts the backend and the dev server (tests/e2e/harness.mjs), drives the
 * installed Microsoft Edge headless with a fresh profile, and checks each
 * step against the DOM, the stores (exposed by the dev build as
 * `window.__kir`) and the backend's own answers:
 *
 * 1. Graph editing in the node view (exec pins): drag a node in, wire data
 *    and control, set a literal in a node's input box, delete, undo, redo,
 *    undo a typed text change, run, lower with a pass off.
 * 2. Every view loads the tour, each and factorial samples.
 * 3. One edit in every view round-trips: the text it produces equals the
 *    backend's text for the graph (and, for statement views, for the AST).
 * 4. No page or console errors anywhere.
 */

import os from "node:os"
import path from "node:path"

import { launch, serverLogs, settled, startServers, stopServers } from "./harness.mjs"

const results = []
let BASE = ""
const PANEL = "[data-test=bottom-panel]"

function assert(cond, message) {
  if (!cond) throw new Error(message)
}

async function step(name, fn) {
  try {
    await fn()
    results.push({ name, ok: true })
    console.log(`  ok    ${name}`)
  } catch (e) {
    results.push({ name, ok: false, error: e.message })
    console.log(`  FAIL  ${name}\n        ${e.message.split("\n").join("\n        ")}`)
    throw e
  }
}

// ---------------------------------------------------------------- page helpers

const store = (page, fn, arg) => page.evaluate(fn, arg)
const text = (page) => store(page, () => window.__kir.doc.text)
const nodeIds = (page) => store(page, () => window.__kir.doc.graph.nodes.map((n) => n.id))

async function open(page, query) {
  await page.goto(`${BASE}/?${query}`)
  await settled(page)
  await page.waitForFunction(() => !document.querySelector(".kg-flow__status .kg-spin"))
}

/** A point of `view`'s canvas (relative to it) with room for a new node below and right of it, clear of nodes and chrome. */
async function emptySpot(page, view, flowId) {
  // Leave a margin round the graph, so a view filled by it has room
  await page.evaluate((f) => window.__kir.flows[f]({ padding: 0.9 }), flowId)
  await page.waitForTimeout(150)
  const spot = await page.evaluate((v) => {
    const surface = document.querySelector(`[data-view=${v}] .kg-flow`).getBoundingClientRect()
    const taken = [...document.querySelectorAll(`[data-view=${v}] .vue-flow__node, [data-view=${v}] .vue-flow__controls, [data-view=${v}] .vue-flow__minimap, [data-view=${v}] .card`)].map((el) => el.getBoundingClientRect())
    const [w, h, margin] = [260, 130, 24]
    for (let y = margin; y + h < surface.height - margin; y += 20)
      for (let x = margin + 40; x + w < surface.width - margin; x += 20) {
        const r = { left: surface.x + x - 40, top: surface.y + y - 14, right: surface.x + x + w, bottom: surface.y + y + h }
        if (!taken.some((t) => t.left < r.right && t.right > r.left && t.top < r.bottom && t.bottom > r.top)) return { x, y }
      }
    return null
  }, view)
  assert(spot, `no empty room on the ${view} canvas`)
  return spot
}

/** The ids of the current graph's nodes that `view` draws no element for. */
const undrawn = (page, view) =>
  store(page, (v) => {
    const drawn = new Set([...document.querySelectorAll(`[data-view=${v}] .vue-flow__node`)].map((el) => el.dataset.id))
    return window.__kir.doc.graph.nodes.map((n) => n.id).filter((id) => !drawn.has(id))
  }, view)

async function center(page, selector) {
  const box = await page.locator(selector).first().boundingBox()
  assert(box, `no element ${selector}`)
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}

const handle = (node, id) => `.vue-flow__handle[data-nodeid="${node}"][data-handleid="${id}"]`

/** The element under a point is `selector` (or inside it): nothing covers it. */
async function uncovered(page, selector, p) {
  const ok = await page.evaluate(([sel, x, y]) => !!document.elementFromPoint(x, y)?.closest(sel), [selector, p.x, p.y])
  assert(ok, `${selector} is covered at (${p.x}, ${p.y})`)
}

/** Drag a wire from one handle to another, after framing both nodes in the view. */
async function wire(page, flowId, from, to, nodes) {
  await page.evaluate(([f, ids]) => window.__kir.flows[f]({ nodes: ids, padding: 0.5 }), [flowId, nodes])
  await page.waitForTimeout(150)
  const a = await center(page, from)
  const b = await center(page, to)
  await uncovered(page, from, a)
  await uncovered(page, to, b)
  await page.mouse.move(a.x, a.y)
  await page.mouse.down()
  await page.mouse.move((a.x + b.x) / 2, (a.y + b.y) / 2, { steps: 8 })
  await page.mouse.move(b.x, b.y, { steps: 8 })
  await page.mouse.up()
}

/** The backend's text for the store's graph, and for its AST, asked for independently. */
const backendTexts = (page) =>
  store(page, async () => {
    const d = window.__kir.doc
    const post = async (route, body) => {
      const res = await fetch(`/api/${route}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, ...d.scope() }),
      })
      return (await res.json()).text
    }
    return {
      fromGraph: await post("text", { graph: d.serializedDoc(), with_meta: d.withMeta }),
      fromAst: await post("ast/text", { ast: d.ast }),
    }
  })

/** After an edit: the text says `expect`, and graph -> text and AST -> text both give that same text. */
async function roundTrips(page, expect, label) {
  await settled(page)
  const t = await text(page)
  assert(expect.every((s) => t.includes(s)), `${label}: text lacks ${JSON.stringify(expect)}:\n${t}`)
  const { fromGraph, fromAst } = await backendTexts(page)
  assert(fromGraph === t, `${label}: /api/text of the graph differs from the text:\n${fromGraph}\n---\n${t}`)
  assert(fromAst === t, `${label}: /api/ast/text of the AST differs from the text:\n${fromAst}\n---\n${t}`)
  const errors = await store(page, () => window.__kir.doc.errorCount)
  assert(errors === 0, `${label}: ${errors} errors after the edit`)
}

// ---------------------------------------------------------------- 1. graph editing

async function graphEditing(page) {
  let mul = null

  await step("nodes view (exec, wires) loads clamp: every node and edge of the graph drawn", async () => {
    await open(page, "sample=clamp&view=split&split=nodes,text&data=wires&control=exec&theme=light")
    await page.waitForSelector("[data-view=nodes] .vue-flow__node")
    const missing = await undrawn(page, "nodes")
    assert(missing.length === 0, `not drawn: ${missing.join(", ")}`)
    const unwired = await store(page, () => {
      const drawn = new Set([...document.querySelectorAll("[data-view=nodes] .kg-wire")].flatMap((g) => g.dataset.keys.split(" ")))
      const key = (e) => `${e.kind}|${e.from.node}|${e.from.port}|${e.to.node}|${e.to.port}`
      return window.__kir.doc.graph.edges.map(key).filter((k) => !drawn.has(k))
    })
    assert(unwired.length === 0, `edges not drawn: ${unwired.join(", ")}`)
    const terminals = await page.locator("[data-view=nodes] .kg-wire[data-ends^='__start|']").count()
    assert(terminals === 1, `${terminals} wires leave Start`)
    assert((await text(page)).includes("(x, y)clamp(avg)"), "unexpected text")
  })

  await step("drag multiply from the palette onto the canvas, drawn where it was dropped", async () => {
    const before = new Set(await nodeIds(page))
    const item = page.locator(".kir-pal-item").filter({ has: page.locator("span", { hasText: /^multiply$/ }) })
    const surface = page.locator("[data-view=nodes] .kg-flow")
    const box = await surface.boundingBox()
    const spot = await emptySpot(page, "nodes", "kir-nodes")
    const unmoved = await page.evaluate(() => [...document.querySelectorAll("[data-view=nodes] .vue-flow__node")].map((el) => [el.dataset.id, el.getBoundingClientRect().x, el.getBoundingClientRect().y]))
    await item.dragTo(surface, { targetPosition: spot })
    await page.waitForFunction(() => window.__kir.doc.graph.nodes.length === 9)
    mul = (await nodeIds(page)).find((id) => !before.has(id))
    const node = await store(page, (id) => window.__kir.doc.graph.nodes.find((n) => n.id === id), mul)
    assert(node.kind === "call" && node.name === "multiply", `dropped ${JSON.stringify(node)}`)
    await page.waitForSelector(`.vue-flow__node[data-id="${mul}"]`)
    await settled(page)
    assert((await text(page)).includes("()multiply(result)"), "text lacks the free multiply")
    // The drop point is the node's top left, less the grab offset (views/shared/GraphCanvas.vue)
    const at = await page.locator(`.vue-flow__node[data-id="${mul}"]`).boundingBox()
    assert(Math.abs(at.x - (box.x + spot.x)) < 60 && Math.abs(at.y - (box.y + spot.y)) < 30, `multiply drawn at ${at.x - box.x}, ${at.y - box.y}, dropped at ${spot.x}, ${spot.y}`)
    for (const [id, x, y] of unmoved) {
      const now = await page.locator(`[data-view=nodes] .vue-flow__node[data-id="${id}"]`).boundingBox()
      assert(now && Math.abs(now.x - x) < 1 && Math.abs(now.y - y) < 1, `${id} moved when multiply was added`)
    }
  })

  await step("wire a data edge x -> multiply.a", async () => {
    const x = await store(page, () => window.__kir.doc.graph.nodes.find((n) => n.outputs?.[0]?.var === "x").id)
    await wire(page, "kir-nodes", handle(x, "data:out:value"), handle(mul, "data:in:a"), [x, mul])
    const ok = await store(
      page,
      ([x, mul]) => window.__kir.doc.graph.edges.some((e) => e.kind === "data" && e.from.node === x && e.to.node === mul && e.to.port === "a"),
      [x, mul],
    )
    assert(ok, "no data edge in the store")
  })

  await step("wire an exec edge last print_val -> multiply", async () => {
    const last = await store(page, () => window.__kir.doc.graph.nodes.filter((n) => n.name === "print_val").at(-1).id)
    await wire(page, "kir-nodes", handle(last, "ctrl:out:out"), handle(mul, "ctrl:in:in"), [last, mul])
    const ok = await store(
      page,
      ([last, mul]) => window.__kir.doc.graph.edges.some((e) => e.kind === "ctrl" && e.from.node === last && e.to.node === mul),
      [last, mul],
    )
    assert(ok, "no control edge in the store")
    await settled(page)
    assert((await text(page)).trimEnd().endsWith("(avg2)print_val()\n(x)multiply(result)"), "multiply not chained last")
  })

  await step("drag multiply: it moves, its wires end on its pins, nothing else moves", async () => {
    const rects = () => page.evaluate(() => Object.fromEntries([...document.querySelectorAll("[data-view=nodes] .vue-flow__node")].map((el) => [el.dataset.id, el.getBoundingClientRect().toJSON()])))
    const before = await rects()
    const head = await page.locator(`.vue-flow__node[data-id="${mul}"] .kg-card__head`).boundingBox()
    // The drag starts on the first pointer move; the node follows the pointer from there
    await page.mouse.move(head.x + 24, head.y + head.height / 2)
    await page.mouse.down()
    await page.mouse.move(head.x + 26, head.y + head.height / 2 + 1)
    await page.mouse.move(head.x + 146, head.y + head.height / 2 + 81, { steps: 10 })
    await page.mouse.up()
    await page.waitForTimeout(200)
    const after = await rects()
    for (const [id, r] of Object.entries(after)) {
      const [dx, dy] = [r.x - before[id].x, r.y - before[id].y]
      if (id === mul) assert(Math.abs(dx - 120) < 3 && Math.abs(dy - 80) < 3, `multiply moved by ${dx}, ${dy}`)
      else assert(Math.abs(dx) < 1 && Math.abs(dy) < 1, `${id} moved by ${dx}, ${dy}`)
    }
    const off = await page.evaluate((id) => {
      const out = []
      const centre = (node, handle) => {
        const r = document.querySelector(`[data-view=nodes] .vue-flow__handle[data-nodeid="${node}"][data-handleid="${handle}"]`)?.getBoundingClientRect()
        return r && { x: r.x + r.width / 2, y: r.y + r.height / 2 }
      }
      for (const g of document.querySelectorAll("[data-view=nodes] .kg-wire")) {
        const [s, sh, t, th] = g.dataset.ends.split("|")
        if (s !== id && t !== id) continue
        const path = g.querySelector(".kg-wire__line")
        const ctm = path.getScreenCTM()
        const at = (len) => new DOMPoint(path.getPointAtLength(len).x, path.getPointAtLength(len).y).matrixTransform(ctm)
        const [a, b] = [at(0), at(path.getTotalLength())]
        const [pa, pb] = [centre(s, sh), centre(t, th)]
        out.push({ ends: g.dataset.ends, source: pa ? Math.hypot(a.x - pa.x, a.y - pa.y) : -1, target: pb ? Math.hypot(b.x - pb.x, b.y - pb.y) : -1 })
      }
      return out
    }, mul)
    // Its two wires, and the view's own wire on to End now that multiply ends the chain
    const own = off.filter((w) => !w.ends.includes("__"))
    assert(own.length === 2 && off.length === 3, `expected multiply's 2 wires and the one to End, found ${off.map((w) => w.ends).join(", ")}`)
    for (const w of off) assert(w.source >= 0 && w.source < 2 && w.target >= 0 && w.target < 2, `wire ${w.ends} ends ${w.source.toFixed(1)} / ${w.target.toFixed(1)} px off its pins`)
  })

  await step("type b = 7 in the node's input box (widget); graph -> text and AST -> text agree", async () => {
    const box = page.locator(`.vue-flow__node[data-id="${mul}"] input.kg-widget`)
    assert((await box.count()) === 1, "expected one widget (a is wired, so only b has a box)")
    await box.fill("7")
    await box.press("Enter")
    const value = await store(page, (id) => window.__kir.doc.graph.nodes.find((n) => n.id === id).inputs.find((p) => p.port === "b").value, mul)
    assert(value === 7, `b is ${JSON.stringify(value)}`)
    await roundTrips(page, ["(x, 7)multiply(result)"], "widget edit")
    assert((await page.locator(".cm-content").innerText()).includes("(x, 7)multiply(result)"), "text view not updated")
  })

  let withMultiply = ""
  await step("delete multiply with the Delete key", async () => {
    withMultiply = await text(page)
    await page.locator(`.vue-flow__node[data-id="${mul}"] .kg-card__head`).click()
    await page.keyboard.press("Delete")
    await page.waitForFunction((id) => !window.__kir.doc.graph.nodes.some((n) => n.id === id), mul)
    await settled(page)
    assert(!(await text(page)).includes("multiply"), "text still has multiply")
  })

  await step("undo (Ctrl+Z) restores multiply, its wires, b = 7 and the text", async () => {
    await page.locator("[data-view=nodes] .kg-flow").click({ position: { x: 30, y: 300 } })
    await page.keyboard.press("Control+z")
    await page.waitForFunction((id) => window.__kir.doc.graph.nodes.some((n) => n.id === id), mul)
    const edges = await store(page, (id) => window.__kir.doc.graph.edges.filter((e) => e.to.node === id).length, mul)
    assert(edges === 2, `${edges} edges into multiply after undo`)
    await settled(page)
    assert((await text(page)) === withMultiply, "text after undo differs")
  })

  await step("redo (toolbar) removes it again", async () => {
    await page.locator("[data-test=redo]").click()
    await page.waitForFunction((id) => !window.__kir.doc.graph.nodes.some((n) => n.id === id), mul)
    await settled(page)
    assert(!(await text(page)).includes("multiply"), "text still has multiply after redo")
  })

  await step("a typed text change reaches every projection, and undo takes it back", async () => {
    const before = await text(page)
    await page.locator(".cm-content").click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type("z = 1\n")
    await page.waitForFunction(() => window.__kir.doc.ast?.body.some((s) => s.type === "assign" && s.target === "z"))
    await settled(page)
    await page.locator("[data-view=nodes] .kg-flow").click({ position: { x: 30, y: 300 } })
    await page.keyboard.press("Control+z")
    await page.waitForFunction(() => !window.__kir.doc.ast?.body.some((s) => s.type === "assign" && s.target === "z"))
    await settled(page)
    assert((await text(page)) === before, "text after undo differs")
  })

  await step("Run: the Run tab shows stdout and final values", async () => {
    await page.locator("header button.btn-primary", { hasText: "Run" }).click()
    await page.waitForFunction(() => window.__kir.doc.runResult)
    const run = await store(page, () => window.__kir.doc.runResult)
    assert(run.ok && run.values.avg === 20 && run.values.avg2 === 47.5, `run result ${JSON.stringify(run)}`)
    const pre = await page.locator(`${PANEL} pre`).first().innerText()
    assert(pre.includes("20.0") && pre.includes("47.5"), `Run tab shows:\n${pre}`)
  })

  await step("Lowered: inline switched off keeps the @def", async () => {
    await page.locator(".kir-tab", { hasText: "Lowered" }).click()
    await page.locator(".kir-pass", { hasText: /^inline$/ }).click()
    await page.locator("header button", { hasText: "Lower" }).click()
    await page.waitForFunction(() => window.__kir.doc.lowerResult?.lowered)
    const shown = await page.locator(`${PANEL} pre`).first().innerText()
    assert(shown.includes("@def (a, b)clamp(result)"), `Lowered tab shows:\n${shown}`)
  })
}

// ---------------------------------------------------------------- 2. every view loads every sample

const VIEW_CHECKS = {
  "nodes&control=frames": async (page, s) => {
    const drawn = await page.locator("[data-view=nodes] .vue-flow__node-card").count()
    assert(drawn > 0, "no cards drawn")
    if (s !== "clamp") assert((await page.locator(".kg-region").count()) > 0, "no control regions drawn")
  },
  "nodes&control=exec": async (page) => {
    assert((await page.locator(".kg-pin--ctrl").count()) > 0, "no exec pins drawn")
  },
  flowchart: async (page) => {
    assert((await page.locator(".kg-robo--start").count()) === 1, "no Start element")
    assert((await page.locator(".kg-robo--variable").count()) > 0, "no VARIABLE elements")
  },
  sequence: async (page) => {
    assert((await page.locator(".ev-tile").count()) > 0, "no EV3 blocks")
    assert((await page.locator(".ev-cont").count()) > 0, "no containers")
  },
  blocks: async (page) => {
    assert((await page.locator(".sb-hat").count()) >= 1, "no hat block")
    assert((await page.locator(".sb-c").count()) > 0, "no C blocks")
  },
  text: async (page) => {
    const shown = await page.locator(".cm-content").innerText()
    assert(shown.length > 20, "no text shown")
  },
}

async function everyView(page) {
  for (const sample of ["tour", "each", "factorial"]) {
    for (const [view, check] of Object.entries(VIEW_CHECKS)) {
      await step(`${view} loads ${sample}`, async () => {
        await open(page, `view=${view}&sample=${sample}`)
        await page.waitForTimeout(300)
        await check(page, sample)
      })
    }
  }
}

// ---------------------------------------------------------------- 3. one edit per view round-trips

async function editsPerView(page) {
  await step("nodes (frames): set x = 3 in an assign node's input box", async () => {
    await open(page, "view=nodes&sample=tour&data=variables&control=frames")
    const id = await store(page, () => {
      const g = window.__kir.doc.graph
      const set = g.nodes.find((n) => n.kind === "set" && n.props.name === "x")
      return g.edges.find((e) => e.to.node === set.id).from.node
    })
    const box = page.locator(`.vue-flow__node[data-id="${id}"] input.kg-widget`)
    await box.fill("3")
    await box.press("Enter")
    await roundTrips(page, ["x = 3\n"], "nodes frames")
  })

  await step("nodes (frames): an assign dropped into a region box joins the end of that block", async () => {
    const target = await page.evaluate(() => {
      const nodes = [...document.querySelectorAll("[data-view=nodes] .vue-flow__node-card")].map((el) => el.getBoundingClientRect())
      // A control region's box (a dataflow block's box is its owner node, and takes no drops into it)
      for (const el of document.querySelectorAll("[data-view=nodes] .vue-flow__node-region")) {
        if (!el.dataset.id.startsWith("region:")) continue
        const r = el.getBoundingClientRect()
        for (let y = r.top + 30; y < r.bottom - 4; y += 4)
          for (let x = r.left + 4; x < r.right - 4; x += 4)
            if (!nodes.some((n) => x > n.left - 2 && x < n.right + 2 && y > n.top - 2 && y < n.bottom + 2)) return { x, y, region: el.dataset.id }
      }
      return null
    })
    assert(target, "no free point inside a region box")
    const rid = target.region.slice("region:".length)
    const before = new Set(await nodeIds(page))
    const item = page.locator(".kir-pal-item").filter({ has: page.locator("span", { hasText: /^assign$/ }) })
    const surface = await page.locator("[data-view=nodes] .kg-flow").boundingBox()
    await item.dragTo(page.locator("[data-view=nodes] .kg-flow"), { targetPosition: { x: target.x - surface.x, y: target.y - surface.y } })
    await page.waitForFunction((n) => window.__kir.doc.graph.nodes.length === n + 1, before.size)
    const added = await store(page, (ids) => window.__kir.doc.graph.nodes.find((n) => !ids.includes(n.id)), [...before])
    assert(added.kind === "assign" && added.region === rid, `dropped ${JSON.stringify(added)} into ${rid}`)
    const name = added.outputs[0].var
    await roundTrips(page, [`    ${name} = 0\n`], "frames drop into a region")
  })

  await step("flowchart: set n = 6 on the '= value' element (inspector)", async () => {
    await open(page, "view=flowchart&sample=factorial")
    const id = await store(page, () => {
      const g = window.__kir.doc.graph
      const set = g.nodes.find((n) => n.kind === "set" && n.props.name === "n")
      return g.edges.find((e) => e.to.node === set.id).from.node
    })
    await page.locator(`.vue-flow__node[data-id="${id}"]`).click()
    await page.waitForFunction((x) => window.__kir.doc.selectedId === x, id)
    const field = page.locator("[data-test=inspector] input").first()
    await field.fill("6")
    await field.press("Enter")
    await roundTrips(page, ["n = 6\n"], "flowchart")
  })

  await step("sequence: edit the boxes parameter box to [1, 2, 3, 4]", async () => {
    await open(page, "view=sequence&sample=each")
    await page.locator(".ev-param .sb-slot", { hasText: "[1, 2, 3]" }).click()
    const field = page.locator(".ev-param input.sb-slot--edit")
    await field.fill("[1, 2, 3, 4]")
    await field.press("Enter")
    await roundTrips(page, ["boxes = [1, 2, 3, 4]"], "sequence")
  })

  await step("blocks: edit 'set n to 5' to 7, then drag 'set counter' above 'set result'", async () => {
    await open(page, "view=blocks&sample=factorial")
    await page.locator(".sb-block", { hasText: /set\s*n/ }).locator(".sb-slot").click()
    const field = page.locator("input.sb-slot--edit")
    await field.fill("7")
    await field.press("Enter")
    await roundTrips(page, ["n = 7\n"], "blocks slot")
    const counter = page.locator("[data-script=main] > .sb-stack > .sb-item", { hasText: /set\s*counter/ }).first()
    const drops = page.locator("[data-script=main] > .sb-stack > .sb-drop")
    await counter.dragTo(drops.nth(1))
    await roundTrips(page, ["n = 7\ncounter = 1\nresult = 1\n"], "blocks drag")
  })

  // A sample without comments or @meta: graph -> text keeps neither, so only there is it the text itself.
  await step("text: type a statement; the graph and AST follow", async () => {
    await open(page, "view=text&sample=each")
    await page.locator(".cm-content").click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type("w = 9\n")
    await page.waitForFunction(() => window.__kir.doc.ast?.body.some((s) => s.type === "assign" && s.target === "w"))
    await roundTrips(page, ["w = 9"], "text")
  })
}

// ---------------------------------------------------------------- main

async function main() {
  console.log("starting backend and dev server…")
  BASE = await startServers()
  const b = await launch({ width: 1500, height: 950 })
  let failed = false
  try {
    await graphEditing(b.page)
    await everyView(b.page)
    await editsPerView(b.page)
    await step("no page errors or console errors", async () => assert(b.errors.length === 0, b.errors.join("\n")))
  } catch {
    failed = true
    const shot = path.join(os.tmpdir(), "kir-editor-e2e-failure.png")
    await b.page.screenshot({ path: shot }).catch(() => {})
    console.log(`screenshot at failure: ${shot}`)
    if (b.errors.length) console.log(`page errors:\n  ${b.errors.join("\n  ")}`)
  } finally {
    await b.close()
  }
  const passed = results.filter((r) => r.ok).length
  console.log(`\n${passed}/${results.length} steps passed${failed ? " (stopped at the first failure)" : ""}`)
  return failed ? 1 : 0
}

let code = 1
try {
  code = await main()
} catch (e) {
  console.error(e)
  console.error(serverLogs())
} finally {
  stopServers()
}
process.exit(code)
