/**
 * The statement views' model: a program's AST (backend core/ast_json.py)
 * grouped into structured items, and back.
 *
 * KIR writes control as a statement plus labelled namespaces. Where the
 * namespaces a statement enters follow it directly, the views show them as
 * one construct: `branch` + its two namespaces is an if / else, `switch` +
 * its case namespaces a switch, `each` + its body a for-each loop,
 * `parallel` + its arms a parallel block, and `()jump(`L`)` directly
 * followed by `L:` a loop. Anything else stays as written (a lone namespace
 * is a labelled block, a jump a jump).
 *
 * The grouping is exact: `flatten(group(block))` returns the block it was
 * given, statement for statement. Moving a construct moves its statement and
 * namespaces together, which keeps where each arm continues (after the last
 * of its namespaces) unchanged.
 */

export const CONTROLLERS = new Set(["branch", "switch", "each", "collect", "parallel"])

/** Labels a controller statement enters, in the order its arms are shown. */
export function armLabels(s) {
  switch (s.type) {
    case "branch":
      return [s.true_label, s.false_label]
    case "switch":
      return [...s.cases.map(([, l]) => l), ...(s.default ? [s.default] : [])]
    case "parallel":
      return [...s.labels]
    case "each":
    case "collect":
      return [s.label]
    default:
      return []
  }
}

/** Group one block of statements into items. */
export function group(block) {
  const items = []
  for (let i = 0; i < block.length; i++) {
    const s = block[i]
    if (CONTROLLERS.has(s.type)) {
      const wanted = new Set(armLabels(s))
      const ns = []
      let j = i + 1
      while (j < block.length && block[j].type === "namespace" && wanted.has(block[j].label) && !ns.some((n) => n.label === block[j].label)) {
        ns.push(block[j])
        j++
      }
      // Only a construct whose every arm follows it is grouped; else it stays as written.
      if (ns.length === wanted.size) {
        items.push({ t: "group", s, arms: ns.map((n) => ({ ns: n, items: group(n.body) })) })
        i = j - 1
        continue
      }
      items.push({ t: "stmt", s })
      continue
    }
    switch (s.type) {
      case "jump": {
        const next = block[i + 1]
        if (next?.type === "namespace" && next.label === s.label) {
          items.push({ t: "loop", s, ns: next, items: group(next.body) })
          i++
        } else items.push({ t: "stmt", s })
        break
      }
      case "namespace":
        items.push({ t: "label", ns: s, items: group(s.body) })
        break
      case "try":
        items.push({ t: "try", s, body: group(s.body), handler: group(s.handler) })
        break
      case "dataflow":
        items.push({ t: "dataflow", s, body: group(s.body) })
        break
      case "def":
        items.push({ t: "def", s, body: group(s.body) })
        break
      default:
        items.push({ t: "stmt", s })
    }
  }
  return items
}

/** Items back to a block of statements. */
export function flatten(items) {
  const out = []
  for (const it of items) {
    switch (it.t) {
      case "group":
        out.push(it.s, ...it.arms.map((a) => ({ ...a.ns, body: flatten(a.items) })))
        break
      case "loop":
        out.push(it.s, { ...it.ns, body: flatten(it.items) })
        break
      case "label":
        out.push({ ...it.ns, body: flatten(it.items) })
        break
      case "try":
        out.push({ ...it.s, body: flatten(it.body), handler: flatten(it.handler) })
        break
      case "dataflow":
      case "def":
        out.push({ ...it.s, body: flatten(it.body) })
        break
      default:
        out.push(it.s)
    }
  }
  return out
}

const isHead = (it) => it.t === "def" || (it.t === "stmt" && it.s.type === "typehints")

/**
 * A program's AST as `{uses, mode, head, body}` on a copy the views may
 * change: `head` holds the `@typehint` blocks and `@def`s (each shown as a
 * script of its own), `body` the top-level statements. Where a definition
 * sits in the text does not change the program; edits write the head first.
 */
export function programTree(ast) {
  const copy = JSON.parse(JSON.stringify(ast))
  const items = group(copy.body)
  return { uses: copy.uses, imports: copy.imports || [], exports: copy.exports || [], mode: copy.mode, head: items.filter(isHead), body: items.filter((it) => !isHead(it)) }
}

export function treeToAst(tree) {
  return { uses: tree.uses, imports: tree.imports || [], exports: tree.exports || [], mode: tree.mode, body: flatten([...tree.head, ...tree.body]) }
}

/** The lists of items an item holds, each with a caption (for drop targets and rendering). */
export function slotsOf(it) {
  switch (it.t) {
    case "group":
      return it.arms.map((a) => a.items)
    case "loop":
    case "label":
      return [it.items]
    case "try":
      return [it.body, it.handler]
    case "dataflow":
    case "def":
      return [it.body]
    default:
      return []
  }
}

/** Whether `inner` is `outer` or sits anywhere inside it (no dropping a block into itself). */
export function contains(outer, inner) {
  if (outer === inner) return true
  return slotsOf(outer).some((list) => list.some((it) => contains(it, inner)))
}

// ---------------------------------------------------------------- names in a program

/** Every name and label a program uses (for fresh names). */
export function usedNames(tree) {
  const names = new Set()
  const walk = (stmts) => {
    for (const s of stmts) {
      for (const k of ["target", "item", "index", "error_name", "label", "true_label", "false_label", "default", "name"])
        if (typeof s[k] === "string") names.add(s[k])
      for (const o of s.outs || []) if (o) names.add(o)
      for (const l of s.labels || []) names.add(l)
      for (const [, l] of s.cases || []) names.add(l)
      for (const p of s.params || []) names.add(p.name)
      for (const k of ["body", "handler"]) if (Array.isArray(s[k])) walk(s[k])
    }
  }
  walk(flatten([...tree.head, ...tree.body]))
  return names
}

export function fresh(names, base) {
  const clean = String(base).replace(/[^A-Za-z0-9_]/g, "_").replace(/__+/g, "_") || "x"
  let name = clean
  for (let i = 2; names.has(name); i++) name = `${clean}${i}`
  names.add(name)
  return name
}

/** Variable names a program writes, for reporters and the sequence view's wires. */
export function variables(tree) {
  const out = new Set()
  const walk = (stmts) => {
    for (const s of stmts) {
      if (s.type === "assign") out.add(s.target)
      for (const o of s.outs || []) if (o) out.add(o)
      if (s.type === "each" || s.type === "collect") for (const n of [s.item, s.index]) if (n) out.add(n)
      if (s.type === "collect") out.add(s.target)
      if (s.type === "try" && s.error_name) out.add(s.error_name)
      for (const p of s.params || []) out.add(p.name)
      for (const k of ["body", "handler"]) if (Array.isArray(s[k])) walk(s[k])
    }
  }
  walk(flatten([...tree.head, ...tree.body]))
  return [...out].sort()
}
