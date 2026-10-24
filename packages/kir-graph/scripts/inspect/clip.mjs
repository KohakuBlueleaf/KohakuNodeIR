/**
 * A close screenshot of one element of the dev gallery, zoomed in on it:
 * node scripts/inspect/clip.mjs "<state>" "<css selector>" <zoom> <out.png>
 */

import { chromium } from "playwright-core"

const [state, selector, zoom, out] = process.argv.slice(2)
const browser = await chromium.launch({ channel: "msedge", headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } })
await page.goto(`http://127.0.0.1:5199/#${state}`)
await page.reload()
await page.waitForTimeout(500)
await page.waitForFunction(() => !document.querySelector(".kg-flow__status .kg-spin"), null, { timeout: 120000 })
await page.waitForTimeout(500)
const el = page.locator(selector).first()
await el.click()
const box = await el.boundingBox()
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
for (let i = 0; i < Number(zoom); i++) {
  await page.mouse.wheel(0, -200)
  await page.waitForTimeout(120)
}
await page.waitForTimeout(400)
const b = await el.boundingBox()
await page.screenshot({ path: out, clip: { x: Math.max(0, b.x - 60), y: Math.max(0, b.y - 50), width: Math.min(900, b.width + 120), height: Math.min(700, b.height + 100) } })
await browser.close()
