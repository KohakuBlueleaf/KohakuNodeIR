/**
 * Wire-to-pin alignment in the rendered dev gallery: for every drawn wire, the
 * screen distance from its path's first point to the centre of its source pin
 * and from its last point to the centre of its target pin.
 * node scripts/checks/anchors.mjs [--tol 1.5] [state ...]
 */

import { chromium } from "playwright-core"

const args = process.argv.slice(2)
const i = args.indexOf("--tol")
const tol = i >= 0 ? Number(args.splice(i, 2)[1]) : 1.5
const states = args.length
  ? args
  : [
      "id=gbc__gbc&view=nodes&graph=gbc",
      "id=gbc__gbc&view=frames&graph=gbc",
      "id=gbc__gbc&view=dataflow&graph=gbc",
      "id=gbc__gbc&view=flowchart&graph=gbc",
      "id=generated__nested&view=nodes&graph=score_all&fold=d1",
      "id=gbc__gbc&view=nodes&graph=expand_all&style=variables",
      "id=generated__nested&view=flowchart&graph=score_all",
      "id=generated__nested&view=frames&graph=score_all&fold=top",
      "id=tour__04_dataflow_and_flags&view=nodes&graph=main",
    ]

const browser = await chromium.launch({ channel: "msedge", headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } })
let failed = 0

for (const state of states) {
  await page.goto(`http://127.0.0.1:5199/#${state}`)
  await page.reload()
  await page.waitForTimeout(500)
  await page.waitForFunction(() => !document.querySelector(".kg-flow__status .kg-spin"), null, { timeout: 120000 })
  await page.waitForTimeout(800)
  const r = await page.evaluate(() => {
    const centre = (el) => {
      const b = el.getBoundingClientRect()
      return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
    }
    const pin = (nodeId, handle) => {
      const node = document.querySelector(`.vue-flow__node[data-id="${CSS.escape(nodeId)}"]`)
      return node && [...node.querySelectorAll(".vue-flow__handle")].find((h) => h.dataset.handleid === handle)
    }
    const out = []
    for (const g of document.querySelectorAll(".kg-wire")) {
      const line = g.querySelector(".kg-wire__line")
      const ctm = line.getScreenCTM()
      const len = line.getTotalLength()
      const at = (s) => new DOMPoint(line.getPointAtLength(s).x, line.getPointAtLength(s).y).matrixTransform(ctm)
      const [source, sourceHandle, target, targetHandle] = g.dataset.ends.split("|")
      const id = `${source}:${sourceHandle} -> ${target}:${targetHandle}`
      const ends = [pin(source, sourceHandle), pin(target, targetHandle)]
      const a = at(0)
      const b = at(len)
      const off = (p, el) => el && { x: (p.x - centre(el).x) / ctm.a, y: (p.y - centre(el).y) / ctm.a }
      const oa = off(a, ends[0])
      const ob = off(b, ends[1])
      const da = oa ? Math.hypot(oa.x, oa.y) * ctm.a : null
      const db = ob ? Math.hypot(ob.x, ob.y) * ctm.a : null
      out.push({ id, da, db, oa, ob, zoom: ctm.a })
    }
    return out
  })
  const measured = r.filter((e) => e.da != null || e.db != null)
  const bad = measured.filter((e) => (e.da ?? 0) > tol * e.zoom || (e.db ?? 0) > tol * e.zoom)
  if (bad.length || !measured.length) failed++
  const worst = bad.sort((x, y) => Math.max(y.da ?? 0, y.db ?? 0) - Math.max(x.da ?? 0, x.db ?? 0)).slice(0, 6)
  console.log(`${bad.length || !measured.length ? "FAIL" : "ok  "} ${state}  wires ${r.length} measured ${measured.length} off ${bad.length}`)
  const fmt = (o) => (o ? `(${o.x.toFixed(1)}, ${o.y.toFixed(1)})` : "-")
  for (const e of worst) console.log(`    ${e.id}  source ${e.da?.toFixed(1)}px ${fmt(e.oa)}  target ${e.db?.toFixed(1)}px ${fmt(e.ob)}  (zoom ${e.zoom.toFixed(2)}, offsets in graph units)`)
}
await browser.close()
process.exit(failed ? 1 : 0)
