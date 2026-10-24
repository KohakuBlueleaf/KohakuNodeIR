/**
 * Running ELK. `configureElk({workerUrl})` runs it in a web worker (the URL of
 * `elkjs/lib/elk-worker.min.js`, e.g. Vite's `?url` import); without one, or
 * when the worker fails or does not answer in `timeoutMs`, ELK runs on the
 * calling thread. Results are cached by their input, so the same graph in the
 * same view is laid out once.
 */

import ElkApi from "elkjs/lib/elk-api.js"

const CACHE_SIZE = 64

let workerUrl = null
let timeoutMs = 20000
let workerElk = null
let localElk = null
const cache = new Map()

export function configureElk(opts = {}) {
  if ("workerUrl" in opts) {
    workerUrl = opts.workerUrl
    workerElk?.terminateWorker?.()
    workerElk = null
  }
  if (opts.timeoutMs) timeoutMs = opts.timeoutMs
}

async function local() {
  if (!localElk) {
    const { default: Elk } = await import("elkjs/lib/elk.bundled.js")
    localElk = new Elk()
  }
  return localElk
}

async function viaWorker(graph) {
  workerElk ||= new ElkApi({ workerUrl })
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("elk worker timeout")), timeoutMs)
  })
  try {
    return await Promise.race([workerElk.layout(graph), timeout])
  } finally {
    clearTimeout(timer)
  }
}

/** FNV-1a over a string, as 8 hex digits. */
export function hashText(s) {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, "0")
}

/** Lay out an ELK graph; `{result, ms, cached}`. */
export async function runElk(graph) {
  const text = JSON.stringify(graph)
  const key = `${hashText(text)}:${text.length}`
  const hit = cache.get(key)
  if (hit) {
    cache.delete(key)
    cache.set(key, hit)
    return { result: hit, ms: 0, cached: true }
  }
  const t0 = performance.now()
  let result = null
  if (workerUrl && typeof Worker !== "undefined") {
    try {
      result = await viaWorker(JSON.parse(text))
    } catch {
      workerElk?.terminateWorker?.()
      workerElk = null
    }
  }
  result ||= await (await local()).layout(JSON.parse(text))
  cache.set(key, result)
  if (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value)
  return { result, ms: performance.now() - t0, cached: false }
}
