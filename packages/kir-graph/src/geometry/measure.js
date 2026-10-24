/**
 * Text widths for geometry, measured with the fonts the stylesheets draw
 * (tokens.css). In a browser a canvas measures them; elsewhere (layout tests
 * in Node) a monospace advance of 0.6 em stands in. Widths are cached per
 * font; `resetMeasure` clears them once web fonts finish loading.
 */

const MONO = `"JetBrains Mono", "Fira Code", ui-monospace, Consolas, monospace`
const SANS = `Inter, system-ui, -apple-system, "Segoe UI", sans-serif`

/** Font roles: [CSS font, size in px, monospace]. */
export const FONTS = {
  title: [`600 12px ${MONO}`, 12, true],
  label: [`11px ${MONO}`, 11, true],
  small: [`10px ${MONO}`, 10, true],
  region: [`600 11px ${MONO}`, 11, true],
  sans: [`12px ${SANS}`, 12, false],
}

let ctx
const cache = new Map()

function context() {
  if (ctx !== undefined) return ctx
  ctx = null
  if (typeof document !== "undefined") ctx = document.createElement("canvas").getContext("2d")
  else if (typeof OffscreenCanvas !== "undefined") ctx = new OffscreenCanvas(1, 1).getContext("2d")
  return ctx
}

/** The width in px of `text` drawn in font role `role`, rounded up. */
export function textWidth(text, role = "label") {
  const s = String(text ?? "")
  const key = `${role}|${s}`
  let w = cache.get(key)
  if (w !== undefined) return w
  const [font, size, mono] = FONTS[role]
  const c = context()
  if (c) {
    c.font = font
    w = Math.ceil(c.measureText(s).width)
  } else w = Math.ceil(s.length * size * (mono ? 0.6 : 0.55))
  cache.set(key, w)
  return w
}

export function resetMeasure() {
  cache.clear()
}

/** Resolves when the document's fonts are loaded (at once outside a browser). */
export async function fontsReady() {
  if (typeof document !== "undefined" && document.fonts?.ready) {
    await document.fonts.ready
    resetMeasure()
  }
}
