/**
 * Screenshots of every view and style: `npm run shots -- <out dir>`.
 *
 * One image per view × style on the light theme, and one per view on the
 * dark theme, for the `tour`, `each` and `factorial` samples where they
 * differ. Fails when a page logs an error.
 */

import { mkdirSync } from "node:fs"
import path from "node:path"

import { launch, serverLogs, settled, startServers, stopServers } from "./harness.mjs"

const OUT = path.resolve(process.argv[2] || "editor_views")

/** [file name, URL query]: view × style on light, then a dark round. */
export const SHOTS = [
  ["nodes-variables-frames-tour", "view=nodes&data=variables&control=frames&sample=tour"],
  ["nodes-variables-exec-tour", "view=nodes&data=variables&control=exec&sample=tour"],
  ["nodes-wires-exec-tour", "view=nodes&data=wires&control=exec&sample=tour"],
  ["nodes-wires-frames-factorial", "view=nodes&data=wires&control=frames&sample=factorial"],
  ["nodes-variables-auto-clamp", "view=nodes&data=variables&control=auto&sample=clamp"],
  ["nodes-variables-frames-each", "view=nodes&data=variables&control=frames&sample=each"],
  ["nodes-variables-exec-def-expand", "view=nodes&data=variables&control=exec&sample=tour&graph=expand"],
  ["flowchart-factorial", "view=flowchart&sample=factorial"],
  ["flowchart-tour", "view=flowchart&sample=tour"],
  ["flowchart-each", "view=flowchart&sample=each"],
  ["sequence-stacked-tour", "view=sequence&lanes=stacked&sample=tour"],
  ["sequence-tabs-tour", "view=sequence&lanes=tabs&sample=tour"],
  ["sequence-stacked-each", "view=sequence&lanes=stacked&sample=each"],
  ["sequence-stacked-factorial", "view=sequence&lanes=stacked&sample=factorial"],
  ["blocks-tour", "view=blocks&sample=tour"],
  ["blocks-each", "view=blocks&sample=each"],
  ["blocks-factorial", "view=blocks&sample=factorial"],
  ["text-tour", "view=text&sample=tour"],
  ["split-nodes-text-each", "view=split&split=nodes,text&control=frames&sample=each"],
  ["split-blocks-sequence-factorial", "view=split&split=blocks,sequence&sample=factorial"],
  ["dark-nodes-frames-tour", "view=nodes&data=variables&control=frames&sample=tour&theme=dark"],
  ["dark-nodes-exec-factorial", "view=nodes&data=wires&control=exec&sample=factorial&theme=dark"],
  ["dark-flowchart-factorial", "view=flowchart&sample=factorial&theme=dark"],
  ["dark-sequence-tour", "view=sequence&sample=tour&theme=dark"],
  ["dark-blocks-tour", "view=blocks&sample=tour&theme=dark"],
  ["dark-text-tour", "view=text&sample=tour&theme=dark"],
]

async function main() {
  mkdirSync(OUT, { recursive: true })
  const base = await startServers()
  const b = await launch({ width: 1600, height: 1000 })
  let failed = 0
  try {
    for (const [name, query] of process.argv[3] ? SHOTS.filter(([n]) => n.includes(process.argv[3])) : SHOTS) {
      const before = b.errors.length
      await b.page.goto(`${base}/?${query}`)
      await settled(b.page)
      // Graph views settle when their layout lands; give fitView and the wires a moment.
      await b.page.waitForFunction(() => !document.querySelector(".kg-flow__status .kg-spin"))
      await b.page.waitForTimeout(700)
      const file = path.join(OUT, `${name}.png`)
      await b.page.screenshot({ path: file })
      const errs = b.errors.slice(before)
      if (errs.length) failed++
      console.log(`${errs.length ? "ERR " : "ok  "} ${file}${errs.length ? `\n      ${errs.join("\n      ")}` : ""}`)
    }
  } finally {
    await b.close()
  }
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
