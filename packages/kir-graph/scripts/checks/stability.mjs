/**
 * Overlay stability check against the dev gallery: with the live overlay
 * ticking, no node or wire element may be created or destroyed, while the
 * overlay itself must visibly change (otherwise the check proves nothing).
 * node scripts/checks/stability.mjs [--ms 3000] [state ...]
 */

import { chromium } from "playwright-core"

const args = process.argv.slice(2)
const i = args.indexOf("--ms")
const ms = i >= 0 ? Number(args.splice(i, 2)[1]) : 3000
const states = args.length
  ? args
  : [
      "id=gbc__gbc&view=nodes&graph=expand_all&overlay=live",
      "id=gbc__gbc&view=flowchart&graph=gbc&overlay=live",
      "id=generated__nested&view=frames&graph=score_all&overlay=live&fold=d1",
      "id=generated__nested&view=blocks&graph=score_all&overlay=live",
      "id=generated__nested&view=sequence&graph=main&overlay=live",
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
  const r = await page.evaluate(async (ms) => {
    const SEL = ".vue-flow__node, .vue-flow__edge, .kg-block, .kg-cblock, .kg-tile, .kg-cont"
    const root = document.querySelector(".kg-root")
    const before = [...root.querySelectorAll(SEL)]
    before.forEach((el) => (el.__kgMark = true))
    let added = 0
    let removed = 0
    let overlay = 0
    const obs = new MutationObserver((list) => {
      for (const m of list) {
        if (m.type === "attributes") overlay++
        for (const n of m.addedNodes) if (n.nodeType === 1 && (n.matches(SEL) || n.querySelector(SEL))) added++
        for (const n of m.removedNodes) if (n.nodeType === 1 && (n.matches(SEL) || n.querySelector(SEL))) removed++
      }
    })
    obs.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["class", "style"] })
    await new Promise((res) => setTimeout(res, ms))
    obs.disconnect()
    const after = [...root.querySelectorAll(SEL)]
    return { elements: before.length, now: after.length, fresh: after.filter((el) => !el.__kgMark).length, added, removed, overlay }
  }, ms)
  const ok = r.elements > 0 && r.now === r.elements && r.fresh === 0 && r.added === 0 && r.removed === 0 && r.overlay > 0
  if (!ok) failed++
  console.log(`${ok ? "ok  " : "FAIL"} ${state}  ${JSON.stringify(r)}`)
}
await browser.close()
process.exit(failed ? 1 : 0)
