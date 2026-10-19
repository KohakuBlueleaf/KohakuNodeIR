/**
 * Browser smoke test of the editor: `npm run test:e2e`.
 *
 * Starts the backend (uvicorn from the repository's .venv, or KIR_PYTHON) and
 * the Vite dev server on their own ports, drives the installed Microsoft Edge
 * headless through playwright-core with a fresh user-data-dir, and checks
 * each step against the DOM, the stores (exposed by the dev build as
 * `window.__kir`) and the backend's own answers.
 */

import { spawn } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { chromium } from "playwright-core"

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const BACKEND = path.resolve(FRONTEND, "../backend")
const REPO = path.resolve(FRONTEND, "../../..")
const PYTHON =
  process.env.KIR_PYTHON ||
  path.join(REPO, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python")
const API_PORT = Number(process.env.KIR_E2E_API_PORT || 48931)
const WEB_PORT = Number(process.env.KIR_E2E_WEB_PORT || 5931)
const BASE = `http://127.0.0.1:${WEB_PORT}`
const PANEL = "[data-test=bottom-panel]"

const children = []
const results = []

function start(cmd, args, opts) {
  const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"], ...opts })
  let log = ""
  child.stdout.on("data", (d) => (log += d))
  child.stderr.on("data", (d) => (log += d))
  child.log = () => log
  children.push(child)
  return child
}

async function waitForUrl(url, timeoutMs = 30000) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    try {
      const res = await fetch(url)
      if (res.ok) return
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  throw new Error(`${url} did not come up`)
}

function assert(cond, message) {
  if (!cond) throw new Error(message)
}

async function step(name, fn) {
  const t0 = Date.now()
  try {
    await fn()
    results.push({ name, ok: true, ms: Date.now() - t0 })
    console.log(`  ok    ${name}`)
  } catch (e) {
    results.push({ name, ok: false, error: e.message })
    console.log(`  FAIL  ${name}\n        ${e.message.split("\n").join("\n        ")}`)
    throw e
  }
}

// ---------------------------------------------------------------- page helpers

const store = (page, fn, arg) => page.evaluate(fn, arg)

/** Wait until no text <-> graph sync is pending or in flight. */
const settled = (page) =>
  page.waitForFunction(() => {
    const d = window.__kir?.doc
    return d && !d.syncing && !d.textPending && !d.layingOut
  })

const nodeIds = (page) => store(page, () => window.__kir.doc.graph.nodes.map((n) => n.id))

async function center(page, selector) {
  const box = await page.locator(selector).first().boundingBox()
  assert(box, `no element ${selector}`)
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}

const handle = (node, id) => `.vue-flow__handle[data-nodeid="${node}"][data-handleid="${id}"]`

/** The element under a point is `selector` (or inside it): nothing (the minimap, a panel) covers it. */
async function uncovered(page, selector, p) {
  const ok = await page.evaluate(
    ([sel, x, y]) => !!document.elementFromPoint(x, y)?.closest(sel),
    [selector, p.x, p.y],
  )
  assert(ok, `${selector} is covered at (${p.x}, ${p.y})`)
}

/** Drag a wire from one handle to another, after framing both nodes in the view. */
async function wire(page, from, to, nodes) {
  await page.evaluate((ids) => window.__kir.flow.fitView({ nodes: ids, padding: 0.5 }), nodes)
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

/** The backend's text for the store's current graph, asked for independently. */
const backendText = (page) =>
  store(page, async () => {
    const d = window.__kir.doc
    const res = await fetch("/api/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph: d.serializedDoc(), with_meta: d.withMeta, ...d.scope() }),
    })
    return (await res.json()).text
  })

// ---------------------------------------------------------------- the scenario

async function scenario(page) {
  let mul = null

  await step("load ?sample=clamp: 8 nodes laid out and drawn", async () => {
    await page.goto(`${BASE}/?sample=clamp&view=split&theme=light`)
    await page.waitForFunction(() => window.__kir?.doc?.layout && window.__kir.doc.graph.nodes.length === 8)
    await settled(page)
    await page.waitForFunction(() => document.querySelectorAll(".vue-flow__node").length === 8)
    const text = await store(page, () => window.__kir.doc.text)
    assert(text.includes("(x, y)clamp(avg)"), `unexpected text:\n${text}`)
  })

  await step("drag multiply from the palette onto the canvas", async () => {
    const before = new Set(await nodeIds(page))
    const item = page.locator(".kir-pal-item").filter({ has: page.locator("span", { hasText: /^multiply$/ }) })
    await item.dragTo(page.locator(".kir-surface"), { targetPosition: { x: 120, y: 120 } })
    await page.waitForFunction(() => window.__kir.doc.graph.nodes.length === 9)
    mul = (await nodeIds(page)).find((id) => !before.has(id))
    const node = await store(page, (id) => window.__kir.doc.graph.nodes.find((n) => n.id === id), mul)
    assert(node.kind === "call" && node.name === "multiply", `dropped ${JSON.stringify(node)}`)
    await page.waitForSelector(`.vue-flow__node[data-id="${mul}"]`)
    await settled(page)
    const text = await store(page, () => window.__kir.doc.text)
    assert(text.includes("()multiply(result)"), `text lacks the free multiply:\n${text}`)
  })

  await step("wire a data edge x.value -> multiply.a", async () => {
    const x = await store(page, () => window.__kir.doc.graph.nodes.find((n) => n.outputs?.[0]?.var === "x").id)
    const drawn = await page.locator(".vue-flow__edge").count()
    await wire(page, handle(x, "data:out:value"), handle(mul, "data:in:a"), [x, mul])
    const ok = await store(
      page,
      ([x, mul]) =>
        window.__kir.doc.graph.edges.some(
          (e) => e.kind === "data" && e.from.node === x && e.from.port === "value" && e.to.node === mul && e.to.port === "a",
        ),
      [x, mul],
    )
    assert(ok, "no data edge in the store")
    await page.waitForFunction((n) => document.querySelectorAll(".vue-flow__edge").length === n + 1, drawn)
  })

  await step("wire a control edge last print_val.out -> multiply.in", async () => {
    const last = await store(page, () => window.__kir.doc.graph.nodes.filter((n) => n.name === "print_val").at(-1).id)
    await wire(page, handle(last, "ctrl:out:out"), handle(mul, "ctrl:in:in"), [last, mul])
    const ok = await store(
      page,
      ([last, mul]) =>
        window.__kir.doc.graph.edges.some((e) => e.kind === "ctrl" && e.from.node === last && e.to.node === mul && e.to.port === "in"),
      [last, mul],
    )
    assert(ok, "no control edge in the store")
    await settled(page)
    const text = await store(page, () => window.__kir.doc.text)
    assert(text.trimEnd().endsWith("(avg2)print_val()\n(x)multiply(result)"), `multiply not chained last:\n${text}`)
  })

  await step("edit literal b = 7 in the inspector; text and /api/text agree", async () => {
    await page.locator(`.vue-flow__node[data-id="${mul}"]`).click()
    const field = page.locator("aside input[placeholder='literal, or wire it']")
    await field.fill("7")
    await field.press("Enter")
    const value = await store(page, (id) => window.__kir.doc.graph.nodes.find((n) => n.id === id).inputs.find((p) => p.port === "b").value, mul)
    assert(value === 7, `b is ${JSON.stringify(value)}`)
    await settled(page)
    const text = await store(page, () => window.__kir.doc.text)
    assert(text.includes("(x, 7)multiply(result)"), `text lacks the call:\n${text}`)
    assert((await backendText(page)) === text, "store text differs from /api/text for the same graph")
    const errors = await store(page, () => window.__kir.doc.errorCount)
    assert(errors === 0, `${errors} errors after the edit`)
    assert((await page.locator(".cm-content").innerText()).includes("(x, 7)multiply(result)"), "text view not updated")
  })

  let withMultiply = ""
  await step("delete multiply with the Delete key", async () => {
    withMultiply = await store(page, () => window.__kir.doc.text)
    await page.locator(`.vue-flow__node[data-id="${mul}"]`).click()
    await page.keyboard.press("Delete")
    await page.waitForFunction((id) => !window.__kir.doc.graph.nodes.some((n) => n.id === id), mul)
    const dangling = await store(page, (id) => window.__kir.doc.graph.edges.filter((e) => e.from.node === id || e.to.node === id).length, mul)
    assert(dangling === 0, `${dangling} edges still touch the deleted node`)
    await settled(page)
    const text = await store(page, () => window.__kir.doc.text)
    assert(!text.includes("multiply"), `text still has multiply:\n${text}`)
    assert((await page.locator(`.vue-flow__node[data-id="${mul}"]`).count()) === 0, "node still drawn")
  })

  await step("undo (Ctrl+Z) restores multiply, its wires, b = 7 and the text", async () => {
    await page.locator(".kir-surface").click({ position: { x: 20, y: 300 } })
    await page.keyboard.press("Control+z")
    await page.waitForFunction((id) => window.__kir.doc.graph.nodes.some((n) => n.id === id), mul)
    const node = await store(page, (id) => window.__kir.doc.graph.nodes.find((n) => n.id === id), mul)
    assert(node.inputs.find((p) => p.port === "b").value === 7, "b lost its literal")
    const edges = await store(page, (id) => window.__kir.doc.graph.edges.filter((e) => e.to.node === id).length, mul)
    assert(edges === 2, `${edges} edges into multiply after undo`)
    await settled(page)
    const text = await store(page, () => window.__kir.doc.text)
    assert(text === withMultiply, `text after undo differs:\n${text}`)
    assert((await backendText(page)) === text, "restored text differs from /api/text for the restored graph")
    await page.waitForSelector(`.vue-flow__node[data-id="${mul}"]`)
  })

  await step("redo (toolbar) removes it again", async () => {
    await page.locator("[data-test=redo]").click()
    await page.waitForFunction((id) => !window.__kir.doc.graph.nodes.some((n) => n.id === id), mul)
    await settled(page)
    const text = await store(page, () => window.__kir.doc.text)
    assert(!text.includes("multiply"), `text still has multiply after redo:\n${text}`)
    assert((await store(page, () => window.__kir.doc.redoDepth)) === 0, "redo stack not empty")
  })

  await step("a typed text change reaches the graph, and undo takes it back", async () => {
    const before = await store(page, () => window.__kir.doc.text)
    await page.locator(".cm-content").click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type("z = 1\n")
    await page.waitForFunction(() => window.__kir.doc.graph.nodes.some((n) => n.outputs?.[0]?.var === "z"))
    await settled(page)
    await page.locator(".kir-surface").click({ position: { x: 20, y: 300 } })
    await page.keyboard.press("Control+z")
    await page.waitForFunction(() => !window.__kir.doc.graph.nodes.some((n) => n.outputs?.[0]?.var === "z"))
    await settled(page)
    const text = await store(page, () => window.__kir.doc.text)
    assert(text === before, `text after undo:\n${text}`)
    assert(!(await page.locator(".cm-content").innerText()).includes("z = 1"), "text view still has the typed line")
  })

  await step("Run: the Run tab shows stdout and final values", async () => {
    await page.locator("header button.btn-primary", { hasText: "Run" }).click()
    await page.waitForFunction(() => window.__kir.doc.runResult)
    const run = await store(page, () => window.__kir.doc.runResult)
    assert(run.ok && run.values.avg === 20 && run.values.avg2 === 47.5, `run result ${JSON.stringify(run)}`)
    const pre = await page.locator(`${PANEL} pre`).first().innerText()
    assert(pre.includes("20.0") && pre.includes("47.5"), `Run tab shows:\n${pre}`)
    assert((await page.locator(`${PANEL} table`).innerText()).includes("avg2"), "final values table missing")
  })

  await step("Lowered: inline switched off keeps the @def; matches /api/lower", async () => {
    await page.locator(".kir-tab", { hasText: "Lowered" }).click()
    await page.locator(".kir-pass", { hasText: /^inline$/ }).click()
    const on = await store(page, () => [...window.__kir.doc.passesOn])
    assert(!on.includes("inline") && !on.includes("version"), `passes on: ${on}`)
    await page.locator("header button", { hasText: "Lower" }).click()
    await page.waitForFunction(() => window.__kir.doc.lowerResult?.lowered)
    const shown = await page.locator(`${PANEL} pre`).first().innerText()
    assert(shown.includes("@def (a, b)clamp(result)"), `Lowered tab shows:\n${shown}`)
    const direct = await store(page, async (passes) => {
      const d = window.__kir.doc
      const res = await fetch("/api/lower", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: d.text, passes, ...d.scope() }),
      })
      return res.json()
    }, on)
    const lowered = await store(page, () => window.__kir.doc.lowerResult)
    assert(direct.lowered === lowered.lowered && direct.semantic_hash === lowered.semantic_hash, "tab differs from /api/lower")
    assert((await page.locator(PANEL).innerText()).includes(lowered.semantic_hash), "hash not shown")
  })
}

// ---------------------------------------------------------------- main

async function main() {
  console.log("starting backend and dev server…")
  start(PYTHON, ["-m", "uvicorn", "kir_editor.app:app", "--port", String(API_PORT)], { cwd: BACKEND })
  start(process.execPath, [path.join(FRONTEND, "node_modules/vite/bin/vite.js"), "--port", String(WEB_PORT), "--strictPort", "--host", "127.0.0.1"], {
    cwd: FRONTEND,
    env: { ...process.env, KIR_API_TARGET: `http://127.0.0.1:${API_PORT}` },
  })
  await waitForUrl(`http://127.0.0.1:${API_PORT}/api/health`)
  await waitForUrl(`${BASE}/`)

  const userDataDir = mkdtempSync(path.join(os.tmpdir(), "kir-editor-e2e-"))
  const context = await chromium.launchPersistentContext(userDataDir, {
    channel: "msedge",
    headless: true,
    viewport: { width: 1500, height: 950 },
  })
  const page = context.pages()[0] || (await context.newPage())
  const pageErrors = []
  page.on("pageerror", (e) => pageErrors.push(`pageerror: ${e.message}`))
  page.on("console", (m) => {
    // The page has no favicon; the browser's request for one is not the app's error.
    if (m.type() === "error" && !m.location().url.endsWith("/favicon.ico"))
      pageErrors.push(`console: ${m.text()} (${m.location().url})`)
  })
  page.setDefaultTimeout(15000)

  let failed = false
  try {
    await scenario(page)
    await step("no page errors or console errors", async () => {
      assert(pageErrors.length === 0, pageErrors.join("\n"))
    })
  } catch {
    failed = true
    const shot = path.join(os.tmpdir(), "kir-editor-e2e-failure.png")
    await page.screenshot({ path: shot }).catch(() => {})
    const state = await store(page, () => {
      const d = window.__kir.doc
      const vp = document.querySelector(".vue-flow__transformationpane")?.style.transform
      return { syncing: d.syncing, textPending: d.textPending, transportError: d.transportError, layoutError: d.layoutError, viewport: vp, drawn: document.querySelectorAll(".vue-flow__node").length, text: d.text }
    }).catch((e) => String(e))
    console.log(`state at failure (screenshot ${shot}):\n${JSON.stringify(state, null, 2)}`)
    if (pageErrors.length) console.log(`page errors:\n  ${pageErrors.join("\n  ")}`)
  } finally {
    await context.close()
    rmSync(userDataDir, { recursive: true, force: true })
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
  for (const c of children) console.error(c.log().slice(-2000))
} finally {
  for (const c of children) c.kill()
}
process.exit(code)
