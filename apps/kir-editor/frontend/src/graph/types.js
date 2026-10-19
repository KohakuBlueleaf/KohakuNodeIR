/**
 * Wire and port colours. Control is iolite; a data wire takes the colour of
 * its type, drawn only from the gem palette: literal types have fixed gems,
 * nominal types hash onto the rest, untyped (`_`) is warm grey.
 */

export const GEM = Object.freeze({
  sapphire: { light: "#D6E3F8", main: "#0F52BA", shadow: "#082567" },
  aquamarine: { light: "#D4EDE8", main: "#4C9989", shadow: "#1B6B5A" },
  taaffeite: { light: "#E8D5ED", main: "#A57EAE", shadow: "#6B4670" },
  iolite: { light: "#DDD0F0", main: "#5A4FCF", shadow: "#312A7A" },
  amber: { light: "#F5E6C8", main: "#D4920A", shadow: "#8B5E00" },
  coral: { light: "#F5D5D5", main: "#D46B6B", shadow: "#8B3A3A" },
  sage: { light: "#D5E8DA", main: "#5A9E6F", shadow: "#3A6B48" },
})

export const CTRL_COLOR = GEM.iolite.main
export const UNTYPED_COLOR = "#A09A92"

const FIXED = {
  int: GEM.sapphire.main,
  float: GEM.aquamarine.main,
  str: GEM.amber.main,
  bool: GEM.coral.main,
  list: GEM.taaffeite.main,
  dict: GEM.sage.main,
  None: UNTYPED_COLOR,
}

// Nominal types: the gem shadows and a few mixes, so they never read as a literal type.
const NOMINAL = [
  GEM.sapphire.shadow,
  GEM.aquamarine.shadow,
  GEM.taaffeite.shadow,
  GEM.amber.shadow,
  GEM.coral.shadow,
  GEM.sage.shadow,
  "#7A6FD8",
  "#B0784A",
]

/** The head name of a type text: `list[Box]` -> list, `Node?` -> Node, `A | B` -> A. */
export function typeHead(type) {
  if (!type || type === "_") return null
  const m = /^\s*([A-Za-z_][\w.]*)/.exec(type)
  return m ? m[1] : null
}

export function typeColor(type) {
  const head = typeHead(type)
  if (!head) return UNTYPED_COLOR
  if (FIXED[head]) return FIXED[head]
  let h = 0
  for (const ch of head) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return NOMINAL[h % NOMINAL.length]
}
