/**
 * Screenshots of the dev gallery (running on --url, default http://127.0.0.1:5199)
 * for a list of review states, with every console error and page error:
 * node scripts/inspect/shots.mjs --out DIR [--zoom N] [state ...]
 *
 * A state is the gallery's URL hash, e.g. "id=gbc__gbc&view=flowchart&theme=dark".
 * Without states, a fixed review set is taken. Exits 1 when any page logged an error.
 */

import { mkdirSync } from "node:fs"
import { join } from "node:path"
import { chromium } from "playwright-core"

const args = process.argv.slice(2)
const take = (name, fallback) => {
  const i = args.indexOf(name)
  return i >= 0 ? args.splice(i, 2)[1] : fallback
}
const url = take("--url", "http://127.0.0.1:5199")
const out = take("--out", "shots")
const width = Number(take("--width", "1680"))
const height = Number(take("--height", "1000"))
const zoom = Number(take("--zoom", "0"))

const DEFAULT = [
  "id=gbc__gbc&view=nodes&graph=gbc",
  "id=gbc__gbc&view=frames&graph=gbc",
  "id=gbc__gbc&view=dataflow&graph=gbc",
  "id=gbc__gbc&view=flowchart&graph=gbc",
  "id=gbc__gbc&view=blocks&graph=gbc",
  "id=gbc__gbc&view=sequence&graph=gbc",
  "id=generated__nested&view=nodes&graph=score_all",
  "id=generated__nested&view=flowchart&graph=score_all&theme=dark",
  "id=generated__nested&view=blocks&graph=score_all&theme=dark",
  "id=generated__nested&view=all&graph=score_all",
  "id=gbc__gbc&view=nodes&graph=gbc&fold=top",
  "id=gbc__gbc&view=nodes&graph=expand_all&style=variables",
]
const states = args.length ? args : DEFAULT

mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ channel: "msedge", headless: true })
const page = await browser.newPage({ viewport: { width, height } })
const errors = []
page.on("console", (m) => m.type() === "error" && errors.push(`[console] ${m.text()}`))
page.on("pageerror", (e) => errors.push(`[page] ${e.message}`))

for (const [i, state] of states.entries()) {
  const before = errors.length
  await page.goto(`${url}/#${state}`)
  await page.reload()
  await page.waitForTimeout(400)
  await page.waitForFunction(() => !document.querySelector(".kg-flow__status .kg-spin"), null, { timeout: 120000 })
  await page.waitForTimeout(900)
  // Statement views have no zoom control; only graph views zoom
  const zoomIn = page.locator(".vue-flow__controls-zoomin")
  for (let z = 0; z < zoom && (await zoomIn.count()); z++) {
    await zoomIn.first().click()
    await page.waitForTimeout(250)
  }
  const file = join(out, `${String(i).padStart(2, "0")}-${state.replace(/[^a-z0-9]+/gi, "_")}.png`)
  await page.screenshot({ path: file })
  console.log(`${errors.length > before ? "ERR" : "ok "} ${file}`)
  for (const e of errors.slice(before)) console.log(`    ${e.slice(0, 400)}`)
}
await browser.close()
process.exit(errors.length ? 1 : 0)
