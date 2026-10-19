/**
 * Browser test harness: start the backend and the Vite dev server on their
 * own ports (or use running ones from KIR_E2E_BASE), and drive the installed
 * Microsoft Edge headless through playwright-core with a fresh profile.
 */

import { spawn } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { chromium } from "playwright-core"

export const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const BACKEND = path.resolve(FRONTEND, "../backend")
const REPO = path.resolve(FRONTEND, "../../..")
const PYTHON =
  process.env.KIR_PYTHON ||
  path.join(REPO, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python")
const API_PORT = Number(process.env.KIR_E2E_API_PORT || 48931)
const WEB_PORT = Number(process.env.KIR_E2E_WEB_PORT || 5931)

const children = []

function start(cmd, args, opts) {
  const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"], ...opts })
  let log = ""
  child.stdout.on("data", (d) => (log += d))
  child.stderr.on("data", (d) => (log += d))
  child.log = () => log
  children.push(child)
  return child
}

async function waitForUrl(url, timeoutMs = 30000) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    try {
      const res = await fetch(url)
      if (res.ok) return
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  throw new Error(`${url} did not come up`)
}

/** Start both servers unless KIR_E2E_BASE names a running dev server; resolves to its base URL. */
export async function startServers() {
  if (process.env.KIR_E2E_BASE) return process.env.KIR_E2E_BASE
  start(PYTHON, ["-m", "uvicorn", "kir_editor.app:app", "--port", String(API_PORT)], { cwd: BACKEND })
  start(
    process.execPath,
    [path.join(FRONTEND, "node_modules/vite/bin/vite.js"), "--port", String(WEB_PORT), "--strictPort", "--host", "127.0.0.1"],
    { cwd: FRONTEND, env: { ...process.env, KIR_API_TARGET: `http://127.0.0.1:${API_PORT}` } },
  )
  await waitForUrl(`http://127.0.0.1:${API_PORT}/api/health`)
  const base = `http://127.0.0.1:${WEB_PORT}`
  await waitForUrl(`${base}/`)
  return base
}

export function stopServers() {
  for (const c of children) c.kill()
}

export function serverLogs() {
  return children.map((c) => c.log().slice(-2000)).join("\n")
}

/** Launch Edge with a fresh profile; returns `{context, page, errors, close}`. */
export async function launch({ width = 1500, height = 950 } = {}) {
  const userDataDir = mkdtempSync(path.join(os.tmpdir(), "kir-editor-e2e-"))
  const context = await chromium.launchPersistentContext(userDataDir, {
    channel: "msedge",
    headless: true,
    viewport: { width, height },
  })
  const page = context.pages()[0] || (await context.newPage())
  const errors = []
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`))
  page.on("console", (m) => {
    // The page has no favicon; the browser's request for one is not the app's error.
    if (m.type() === "error" && !m.location().url.endsWith("/favicon.ico"))
      errors.push(`console: ${m.text()} (${m.location().url})`)
  })
  page.setDefaultTimeout(15000)
  return {
    context,
    page,
    errors,
    async close() {
      await context.close()
      rmSync(userDataDir, { recursive: true, force: true })
    },
  }
}

/** Wait until no text <-> graph sync is pending or in flight. */
export const settled = (page) =>
  page.waitForFunction(() => {
    const d = window.__kir?.doc
    return d && d.ast && !d.syncing && !d.textPending
  })
