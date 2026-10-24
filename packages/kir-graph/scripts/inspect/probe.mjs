/**
 * Evaluates an expression in the dev gallery after a state loads and prints the
 * result as JSON: node scripts/inspect/probe.mjs "<state>" "<js expression>"
 */

import { chromium } from "playwright-core"

const [state, expr] = process.argv.slice(2)
const browser = await chromium.launch({ channel: "msedge", headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } })
page.on("pageerror", (e) => console.log(`[page] ${e.message}`))
await page.goto(`http://127.0.0.1:5199/#${state}`)
await page.reload()
await page.waitForTimeout(500)
await page.waitForFunction(() => !document.querySelector(".kg-flow__status .kg-spin"), null, { timeout: 120000 })
await page.waitForTimeout(600)
console.log(JSON.stringify(await page.evaluate(expr), null, 1))
await browser.close()
