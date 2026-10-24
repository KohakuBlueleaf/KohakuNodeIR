/**
 * A made-up runtime for the gallery: every statement gets a heat, a status and
 * badges that drift with time `t` (seconds), and data wires from hot
 * statements run. Deterministic per node key, so a frame is reproducible.
 */

import { edgeKey, isStatement, nodeKey } from "@kohaku/kir-graph"

function seeded(key) {
  let h = 2166136261
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619) >>> 0
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0
    h = Math.imul(h ^ (h >>> 13), 3266489909) >>> 0
    return ((h ^= h >>> 16) >>> 0) / 4294967296
  }
}

export function simulate(model, t) {
  const nodes = new Map()
  const heatOf = new Map()
  for (const n of model.graph.nodes) {
    if (!isStatement(n)) continue
    const key = nodeKey(n)
    const r = seeded(key)
    const [phase, speed, base, kind] = [r() * 6.28, 0.4 + r() * 1.2, r(), r()]
    if (base < 0.25) continue
    const heat = Math.max(0, Math.min(1, 0.5 + 0.5 * Math.sin(t * speed + phase) * base))
    heatOf.set(n.id, heat)
    const rate = Math.round(heat * 120 * base)
    const p90 = Math.round(20 + 600 * heat * kind)
    const status = kind > 0.97 ? "error" : heat > 0.78 ? "running" : heat < 0.22 ? "waiting" : "ok"
    const badges = [{ text: `${rate}/s` }, { text: `p90 ${p90}ms`, tone: p90 > 450 ? "warn" : "muted" }]
    if (kind > 0.97) badges.push({ text: "3 errors", tone: "bad" })
    nodes.set(key, { heat, status, badges, ...(kind > 0.85 ? { note: `queue ${Math.round(heat * 40)}` } : {}) })
  }
  const edges = new Map()
  for (const e of model.graph.edges) {
    const h = heatOf.get(e.from.node)
    if (h == null) continue
    edges.set(edgeKey(e), { weight: h, active: e.kind === "data" && h > 0.6, ...(h > 0.9 && e.kind === "data" ? { label: `${Math.round(h * 90)}/s` } : {}) })
  }
  return { nodes, edges }
}
