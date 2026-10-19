/**
 * Edits of a statement tree (program/structure.js) shared by the blocks and
 * sequence views: moving, inserting and removing items in their lists.
 */

import { slotsOf } from "@/program/structure"

/** The item being dragged inside a statement view: `{item, from: list}` or null. */
export const dragState = { current: null }

export const ITEM_MIME = "application/x-kir-item"
export const NODE_MIME = "application/x-kir-node"
export const VAR_MIME = "application/x-kir-var"

/** Move `item` out of list `from` to `index` in list `to`; false when it would land inside itself. */
export function moveItem(item, from, to, index) {
  if (from === to) {
    const at = from.indexOf(item)
    if (at < 0) return false
    from.splice(at, 1)
    to.splice(at < index ? index - 1 : index, 0, item)
    return true
  }
  // `to` must not be one of the item's own lists (or deeper).
  if (ownsList(item, to)) return false
  const at = from.indexOf(item)
  if (at < 0) return false
  from.splice(at, 1)
  to.splice(index, 0, item)
  return true
}

function ownsList(item, list) {
  const lists = []
  const walk = (it) => {
    for (const l of listsOf(it)) {
      lists.push(l)
      l.forEach(walk)
    }
  }
  walk(item)
  return lists.includes(list)
}

const listsOf = slotsOf

export function removeItem(item, from) {
  const at = from.indexOf(item)
  if (at >= 0) from.splice(at, 1)
}
