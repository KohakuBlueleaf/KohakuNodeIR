/**
 * The editor backend (apps/kir-editor/backend). Every call returns the JSON
 * body; user errors arrive as `diagnostics`, so only transport failures throw.
 */

async function post(path, body) {
  const res = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`)
  return res.json()
}

/** `scope`: `{signatures: [kirsig json], use_demo: bool}`; `data`: "variables" or "wires". */
export const textToGraph = (text, scope, data) => post("graph", { text, data, ...scope })
export const graphToText = (graph, scope, withMeta) =>
  post("text", { graph, with_meta: withMeta, ...scope })
export const astToText = (ast, scope) => post("ast/text", { ast, ...scope })
export const checkText = (text, scope) => post("check", { text, ...scope })
/** `passes`: optimization passes to run, in order; null runs all, [] runs the program as written. */
export const lowerText = (text, scope, passes) => post("lower", { text, passes, ...scope })
export const runText = (text, scope, passes) => post("run", { text, passes, ...scope })

export async function listPasses() {
  const res = await fetch("/api/passes")
  if (!res.ok) throw new Error(`passes: HTTP ${res.status}`)
  return (await res.json()).passes
}

export async function listSignatures() {
  const res = await fetch("/api/signatures")
  if (!res.ok) throw new Error(`signatures: HTTP ${res.status}`)
  return (await res.json()).libraries
}
