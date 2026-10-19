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
    /* storage unavailable: the preference lasts this session only */
  }
}

export const VIEWS = [
  { id: "graph", label: "Graph", icon: "i-carbon-flow" },
  { id: "split", label: "Split", icon: "i-carbon-column" },
  { id: "text", label: "Text", icon: "i-carbon-code" },
  { id: "blocks", label: "Blocks", icon: "i-carbon-blockchain" },
]

export const useUiStore = defineStore("ui", {
  state: () => ({
    view: readPref("kir-view", "split"),
    bottomTab: "problems",
    bottomOpen: true,
    dark: false,
    /** `{line, nonce}`: the text view scrolls to and selects this line when it changes. */
    reveal: null,
  }),

  actions: {
    setView(view) {
      this.view = view
      writePref("kir-view", view)
    },

    showBottom(tab) {
      this.bottomTab = tab
      this.bottomOpen = true
    },

    revealLine(line) {
      if (line == null) return
      if (this.view === "graph" || this.view === "blocks") this.setView("split")
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
