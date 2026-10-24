/** Icons per node kind, region tone and overlay status: one table for every view. */

export const KIND_ICON = {
  call: "function",
  defcall: "function-math",
  assign: "assignment",
  branch: "flow-connection",
  switch: "tree-view-alt",
  merge: "direction-merge",
  loop: "renew",
  each: "repeat",
  collect: "repeat",
  parallel: "split",
  try: "warning-alt",
  except: "warning-alt-filled",
  inputs: "login",
  outputs: "logout",
  dataflow: "data-share",
  namespace: "tag",
  get: "download",
  set: "upload",
  start: "flag-filled",
}

export const kindIcon = (kind) => KIND_ICON[kind] || "function"

/** Overlay statuses, worst last: a collapsed region shows the worst of its statements. */
export const STATUSES = ["idle", "ok", "waiting", "running", "warn", "error"]

export const STATUS_ICON = {
  idle: "pause-filled",
  ok: "checkmark-filled",
  waiting: "circle-dash",
  running: "play-filled-alt",
  warn: "warning-filled",
  error: "error-filled",
}

export const worstStatus = (a, b) => (STATUSES.indexOf(a) >= STATUSES.indexOf(b) ? a : b)
