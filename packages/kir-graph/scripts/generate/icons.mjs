/**
 * Writes src/render/icons.js: the Carbon icons the views draw, as SVG bodies, so
 * the library needs no icon toolchain: node scripts/generate/icons.mjs
 */

import { readFileSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"

const NAMES = [
  "function",
  "function-math",
  "assignment",
  "flow-connection",
  "tree-view-alt",
  "direction-merge",
  "repeat",
  "split",
  "warning-alt",
  "warning-alt-filled",
  "login",
  "logout",
  "data-share",
  "renew",
  "tag",
  "download",
  "upload",
  "chevron-down",
  "chevron-right",
  "checkmark-filled",
  "error-filled",
  "warning-filled",
  "pause-filled",
  "play-filled-alt",
  "circle-dash",
  "flag-filled",
]

const require = createRequire(import.meta.url)
const set = JSON.parse(readFileSync(require.resolve("@iconify-json/carbon/icons.json"), "utf8"))
const size = set.width || 32
const out = {}
for (const name of NAMES) {
  const icon = set.icons[name] || set.icons[set.aliases?.[name]?.parent]
  if (!icon) throw new Error(`no carbon icon ${name}`)
  out[name] = { body: icon.body, size: icon.width || size }
}
const text = `/** Carbon icons (@iconify-json/carbon, Apache-2.0) as SVG bodies; written by scripts/generate/icons.mjs. */\n\nexport const ICONS = ${JSON.stringify(out, null, 1)}\n`
writeFileSync(new URL("../../src/render/icons.js", import.meta.url), text)
console.log(`wrote ${NAMES.length} icons`)
