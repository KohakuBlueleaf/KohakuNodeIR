/**
 * Node libraries: what the backend knows (kir.std, demo, the signature
 * directory) plus signature files the user loaded. Resolves a call's name to
 * its signature the way `NodeEnv.resolve` does: `@def`, aliased `@use`,
 * unaliased libraries, then kir.std.
 */

import { defineStore } from "pinia"

import { listSignatures } from "@/api/backend"

export const useLibraryStore = defineStore("library", {
  state: () => ({
    catalog: [],
    uploaded: [],
    useDemo: true,
    error: null,
  }),

  getters: {
    /** What every backend request carries. */
    scope: (s) => ({ signatures: s.uploaded, use_demo: s.useDemo }),

    libraries: (s) => [
      ...s.catalog,
      ...s.uploaded.map((lib) => ({ ...lib, source: "loaded file", runnable: false })),
    ],
  },

  actions: {
    async load() {
      try {
        this.catalog = await listSignatures()
        this.error = null
      } catch (e) {
        this.error = String(e.message || e)
      }
    },

    addSignatureFile(data) {
      if (data?.kirsig !== 1 || !data.library || !Array.isArray(data.nodes))
        throw new Error("not a .kirsig.json file (kirsig 1)")
      this.uploaded = [...this.uploaded.filter((l) => l.library !== data.library), data]
    },

    removeUploaded(name) {
      this.uploaded = this.uploaded.filter((l) => l.library !== name)
    },

    library(name) {
      return this.libraries.find((l) => l.library === name) || null
    },

    /** `{kind: "def", graph}`, `{kind: "node", library, sig}` or null. */
    resolveCall(name, doc) {
      const def = doc?.graphs?.find((g) => g.name === name && g.name !== "main")
      if (def) return { kind: "def", graph: def }
      const find = (libName, node) => {
        const lib = this.library(libName)
        const sig = lib?.nodes?.find((n) => n.name === node)
        return sig ? { kind: "node", library: libName, sig } : null
      }
      const dot = name.indexOf(".")
      if (dot > 0) {
        const head = name.slice(0, dot)
        const use = doc?.uses?.find((u) => u.alias === head)
        if (use) return find(use.library, name.slice(dot + 1))
      }
      const unaliased = [
        ...(doc?.uses || []).filter((u) => !u.alias).map((u) => u.library),
        ...(this.useDemo ? ["demo"] : []),
        ...this.uploaded.map((l) => l.library),
      ]
      for (const libName of unaliased) {
        const hit = find(libName, name)
        if (hit) return hit
      }
      return find("kir.std", name)
    },

    /**
     * How a call to `node` of `libName` is written in this document, and the
     * `@use` entry to add when the library is not reachable yet.
     */
    callName(libName, node, doc) {
      if (libName === "kir.std") return { name: node }
      const use = doc?.uses?.find((u) => u.library === libName)
      if (use) return { name: use.alias ? `${use.alias}.${node}` : node }
      if (libName === "demo" && this.useDemo) return { name: node }
      if (this.uploaded.some((l) => l.library === libName)) return { name: node }
      return { name: node, use: { library: libName, alias: null } }
    },
  },
})
