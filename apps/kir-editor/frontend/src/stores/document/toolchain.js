/** The toolchain on the program's text: which passes run, and check, lower and run. */

import { checkText, listPasses, lowerText, runText } from "@/api/backend"

export const toolchainActions = {
  async loadPasses() {
    const passes = await this.call(listPasses)
    if (!passes) return
    this.passCatalog = passes
    this.passesOn = passes.map((p) => p.name)
  },

  /** Switch a pass; switching one on also switches on what it needs, off also what needs it. */
  togglePass(name) {
    const on = new Set(this.passesOn)
    const needs = (n) => this.passCatalog.find((p) => p.name === n)?.needs || []
    if (on.has(name)) {
      const drop = (n) => {
        on.delete(n)
        for (const p of this.passCatalog) if (on.has(p.name) && needs(p.name).includes(n)) drop(p.name)
      }
      drop(name)
    } else {
      const add = (n) => {
        on.add(n)
        for (const r of needs(n)) if (!on.has(r)) add(r)
      }
      add(name)
    }
    this.passesOn = this.passCatalog.map((p) => p.name).filter((n) => on.has(n))
  },

  /** The passes to send: null when all are on (the backend default). */
  selectedPasses() {
    return this.passesOn.length === this.passCatalog.length ? null : [...this.passesOn]
  },

  async check() {
    this.busy = "check"
    const res = await this.call(() => checkText(this.text, this.scope()))
    this.busy = null
    if (res) this.diagnostics = res.diagnostics
  },

  async lower() {
    this.busy = "lower"
    const res = await this.call(() => lowerText(this.text, this.scope(), this.selectedPasses()))
    this.busy = null
    if (res) {
      this.lowerResult = res
      this.diagnostics = res.diagnostics
    }
  },

  async run() {
    this.busy = "run"
    const res = await this.call(() => runText(this.text, this.scope(), this.selectedPasses()))
    this.busy = null
    if (res) {
      this.runResult = res
      this.diagnostics = res.diagnostics
    }
  },
}
