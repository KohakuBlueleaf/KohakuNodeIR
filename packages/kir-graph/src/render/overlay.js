/**
 * Live data drawn over a graph without laying it out again.
 *
 * A node entry (keyed by the node's path, else its id: `nodeKey`):
 * `{heat: 0..1, status: "idle"|"ok"|"waiting"|"running"|"warn"|"error",
 *   badges: [{text, tone?: "muted"|"accent"|"good"|"warn"|"bad", title?}], note?: string}`.
 * An edge entry (keyed by `edgeKey`): `{weight: 0..1, label?: string, active?: bool}`.
 * A region entry (keyed by region id): like a node entry; a collapsed region
 * without one shows the hottest heat and worst status of its statements.
 *
 * The store holds one reactive map per kind; `sync` replaces only the entries
 * that changed, so a component reading one key re-renders when that key does.
 */

import { inject, provide, reactive, ref } from "vue"

const KEY = Symbol("kir-graph")

/**
 * The shared state of one KirGraph: overlay maps, the selection and hovered
 * key, the variable name hovered or picked (`hoveredName`, `pickedName`:
 * every element of that name is marked), the collapsed region ids, the wire
 * style ("rail" | "plain"), whether the graph is editable, and the
 * `select(selection)` / `toggle(regionId)` / `edit({id, port, value})`
 * actions the KirGraph installs, and the `validConnection(c)` check a graph
 * view gives its pins.
 */
export function createGraphState() {
  return {
    nodes: reactive(new Map()),
    edges: reactive(new Map()),
    regions: reactive(new Map()),
    selected: ref(null),
    hovered: ref(null),
    hoveredName: ref(null),
    pickedName: ref(null),
    collapsed: ref(new Set()),
    wireStyle: ref("rail"),
    editable: ref(false),
    select: null,
    open: null,
    toggle: null,
    edit: null,
    validConnection: null,
  }
}

/** Write `source` (a Map or an object) into `target`, touching only changed or removed keys. */
export function syncMap(target, source) {
  const next = source instanceof Map ? source : new Map(Object.entries(source || {}))
  for (const k of [...target.keys()]) if (!next.has(k)) target.delete(k)
  for (const [k, v] of next) if (target.get(k) !== v) target.set(k, v)
}

export function provideGraphState(state) {
  provide(KEY, state)
}

export const useGraphState = () => inject(KEY)

/** The variable a node reads or writes, when it is a variable or parameter element. */
export const dataName = (node) => (node && (node.kind === "get" || node.kind === "set") ? (node.props?.name ?? null) : null)

/** Whether `node` names the variable hovered, else the one picked. */
export function sameName(state, node) {
  const name = dataName(node)
  return !!name && name === (state.hoveredName.value ?? state.pickedName.value)
}

/** CSS variables of a node entry's heat for a component's style. */
export function heatStyle(entry) {
  if (!entry || entry.heat == null) return {}
  return { "--kg-heat": String(Math.max(0, Math.min(1, entry.heat))) }
}
