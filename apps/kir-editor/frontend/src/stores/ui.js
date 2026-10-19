/**
 * View choices: which projection of the program is shown and how. Every knob
 * persists per viewer (localStorage); URL parameters override it for one load:
 * ?view=nodes|flowchart|sequence|blocks|text|split &split=<a>,<b>
 * &data=variables|wires &control=exec|frames|auto &lanes=stacked|tabs &theme=light|dark
 */

import { defineStore } from "pinia"

function readPref(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function writePref(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage unavailable: the preference lasts this page only */
  }
}

export const VIEWS = [
  { id: "nodes", label: "Nodes", icon: "i-carbon-flow", hint: "ComfyUI / Blender style node graph" },
  { id: "flowchart", label: "Flowchart", icon: "i-carbon-flow-stream", hint: "ROBO Pro style flowchart" },
  { id: "sequence", label: "Sequence", icon: "i-carbon-chart-relationship", hint: "LEGO EV3 style sequence beam" },
  { id: "blocks", label: "Blocks", icon: "i-carbon-blockchain", hint: "Scratch style blocks" },
  { id: "text", label: "Text", icon: "i-carbon-code", hint: "KIR text" },
]

export const KNOBS = {
  data: ["variables", "wires"],
  control: ["exec", "frames", "auto"],
  lanes: ["stacked", "tabs"],
}

const ONE_VIEW = VIEWS.map((v) => v.id)
const pick = (value, allowed, fallback) => (allowed.includes(value) ? value : fallback)

function splitFrom(text) {
  const parts = String(text || "").split(",")
  return parts.length === 2 && parts.every((p) => ONE_VIEW.includes(p)) && parts[0] !== parts[1]
    ? parts
    : null
}

export const useUiStore = defineStore("ui", {
  state: () => ({
    view: pick(readPref("kir-view", "nodes"), [...ONE_VIEW, "split"], "nodes"),
    split: splitFrom(readPref("kir-split", "")) || ["nodes", "text"],
    data: pick(readPref("kir-data", "variables"), KNOBS.data, "variables"),
    control: pick(readPref("kir-control", "auto"), KNOBS.control, "auto"),
    lanes: pick(readPref("kir-lanes", "stacked"), KNOBS.lanes, "stacked"),
    bottomTab: "problems",
    bottomOpen: true,
    dark: false,
    /** `{line, nonce}`: the text view scrolls to and selects this line when it changes. */
    reveal: null,
  }),

  getters: {
    /** The views on screen, left to right. */
    shown: (s) => (s.view === "split" ? s.split : [s.view]),
  },

  actions: {
    setView(view) {
      this.view = pick(view, [...ONE_VIEW, "split"], this.view)
      writePref("kir-view", this.view)
    },

    setSplit(side, view) {
      const next = [...this.split]
      next[side] = view
      if (next[0] === next[1]) next[1 - side] = this.split[side]
      this.split = next
      writePref("kir-split", next.join(","))
    },

    setKnob(knob, value) {
      if (!KNOBS[knob]?.includes(value)) return
      this[knob] = value
      writePref(`kir-${knob}`, value)
    },

    /** Apply URL parameters for this page load (not persisted). */
    fromUrl(params) {
      if (params.get("view")) this.view = pick(params.get("view"), [...ONE_VIEW, "split"], this.view)
      const split = splitFrom(params.get("split"))
      if (split) this.split = split
      for (const knob of Object.keys(KNOBS)) {
        if (params.get(knob)) this[knob] = pick(params.get(knob), KNOBS[knob], this[knob])
      }
    },

    showBottom(tab) {
      this.bottomTab = tab
      this.bottomOpen = true
    },

    revealLine(line) {
      if (line == null) return
      if (!this.shown.includes("text")) {
        this.split = [this.shown[0] === "text" ? "nodes" : this.shown[0], "text"]
        this.view = "split"
      }
      this.reveal = { line, nonce: Date.now() }
    },

    /** `forced`: "light" or "dark" for this page load only (URL parameter). */
    initTheme(forced = null) {
      const stored = forced || readPref("kir-theme", "system")
      this.dark =
        stored === "dark" ||
        (stored !== "light" && window.matchMedia?.("(prefers-color-scheme: dark)").matches)
      document.documentElement.classList.toggle("dark", this.dark)
    },

    toggleTheme() {
      this.dark = !this.dark
      document.documentElement.classList.toggle("dark", this.dark)
      writePref("kir-theme", this.dark ? "dark" : "light")
    },
  },
})
