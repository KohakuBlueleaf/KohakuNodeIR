/**
 * backend.js — Typed API helpers for the KohakuNodeIR backend.
 *
 * All REST calls go through Vite's /api proxy → localhost:48888 in dev.
 * In production the server must serve the frontend at the same origin or
 * set a CORS-friendly reverse proxy.
 *
 * WebSocket helpers construct a URL that respects the current page origin
 * so they also work through the Vite WS proxy.
 */

const API_BASE = '/api'

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function _post(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const errBody = await res.json()
      detail = errBody.detail ?? errBody.error ?? detail
    } catch {
      // ignore parse error
    }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

async function _get(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    const err = new Error(res.statusText)
    err.status = res.status
    throw err
  }
  return res.json()
}

/**
 * Build a WebSocket URL for a backend path.
 * Uses the same host/port as the current page so it goes through the Vite
 * dev proxy (which is configured to proxy WS on /api too).
 */
function _wsUrl(path) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${API_BASE}${path}`
}

// ---------------------------------------------------------------------------
// REST — node registry
// ---------------------------------------------------------------------------

/**
 * Fetch metadata for all registered node types from the backend.
 * @returns {Promise<object[]>}
 */
export async function listNodes() {
  return _get('/nodes')
}

/**
 * Register (or update) a user-defined node type.
 * @param {{ name, type, category, description, inputs, outputs, code }} definition
 * @returns {Promise<{ success: boolean, type: string }>}
 */
export async function registerNode(definition) {
  return _post('/nodes/register', definition)
}

/**
 * Delete a user-defined node type.
 * @param {string} typeName
 * @returns {Promise<{ success: boolean, type: string }>}
 */
export async function deleteNode(typeName) {
  const res = await fetch(`${API_BASE}/nodes/${encodeURIComponent(typeName)}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const errBody = await res.json()
      detail = errBody.detail ?? errBody.error ?? detail
    } catch {
      // ignore
    }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// REST — execution
// ---------------------------------------------------------------------------

/**
 * Execute a KIR source string synchronously.
 * Returns { success, output, variables, error? }.
 * @param {string} kirSource
 * @returns {Promise<object>}
 */
export async function executeKir(kirSource) {
  return _post('/execute', { kir_source: kirSource })
}

/**
 * Compile a .kirgraph object (L1) to L3 KIR and execute it synchronously.
 * Returns { success, output, variables, kir_source, error? }.
 * @param {object} kirgraph
 * @returns {Promise<object>}
 */
export async function executeKirgraph(kirgraph) {
  return _post('/execute/kirgraph', { kirgraph })
}

/**
 * Compile a .kirgraph object to KIR text without executing.
 * @param {object} kirgraph
 * @param {2|3} [level=3]  2 = with @meta, 3 = stripped
 * @returns {Promise<{ kir_text: string, level: number }>}
 */
export async function compileKirgraph(kirgraph, level = 3) {
  return _post('/compile', { kirgraph, level })
}

/**
 * Decompile KIR source text back to a .kirgraph object.
 * @param {string} kirSource
 * @returns {Promise<{ kirgraph: object }>}
 */
export async function decompileKir(kirSource) {
  return _post('/decompile', { kir_source: kirSource })
}

// ---------------------------------------------------------------------------
// WebSocket — streaming execution
// ---------------------------------------------------------------------------

/**
 * Execute KIR source with streaming events over a WebSocket.
 *
 * The backend expects messages of shape { type: "execute", kir_source: "..." }.
 * It emits:
 *   { type: "started" }
 *   { type: "output",    data: "..." }   — stdout lines
 *   { type: "error",     message: "..." }
 *   { type: "variable",  name: "...", value: ... }
 *   { type: "completed", variables: {...} }
 *
 * @param {string} kirSource
 * @param {{ onOutput, onError, onVariable, onCompleted, onStarted }} callbacks
 * @returns {{ ws: WebSocket, cancel: () => void }}
 */
export function executeKirStreaming(kirSource, callbacks = {}) {
  const { onOutput, onError, onVariable, onCompleted, onStarted } = callbacks
  const ws = new WebSocket(_wsUrl('/ws/execute'))

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'execute', kir_source: kirSource }))
  }

  ws.onmessage = (event) => {
    let msg
    try {
      msg = JSON.parse(event.data)
    } catch {
      onOutput?.(event.data)
      return
    }

    switch (msg.type) {
      case 'started':
        onStarted?.()
        break
      case 'output':
      case 'stdout':
        onOutput?.(msg.data ?? msg.text ?? '')
        break
      case 'error':
      case 'stderr':
        onError?.(msg.message ?? msg.data ?? msg.text ?? '')
        break
      case 'variable':
        onVariable?.(msg.name, msg.value)
        break
      case 'completed':
      case 'done':
      case 'finished':
        onCompleted?.(msg.variables ?? {})
        ws.close(1000)
        break
      default:
        // Unknown message type — ignore silently
        break
    }
  }

  return {
    ws,
    cancel() {
      ws.close(1000)
    },
  }
}

/**
 * Compile a .kirgraph and execute with streaming events over a WebSocket.
 *
 * Emits the same events as executeKirStreaming, plus:
 *   { type: "compiled", kir_source: "..." }  — before execution starts
 *
 * @param {object} kirgraph
 * @param {{ onOutput, onError, onVariable, onCompleted, onStarted, onCompiled }} callbacks
 * @returns {{ ws: WebSocket, cancel: () => void }}
 */
export function executeKirgraphStreaming(kirgraph, callbacks = {}) {
  const { onOutput, onError, onVariable, onCompleted, onStarted, onCompiled } = callbacks
  const ws = new WebSocket(_wsUrl('/ws/execute/kirgraph'))

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'execute', kirgraph }))
  }

  ws.onmessage = (event) => {
    let msg
    try {
      msg = JSON.parse(event.data)
    } catch {
      onOutput?.(event.data)
      return
    }

    switch (msg.type) {
      case 'compiled':
        onCompiled?.(msg.kir_source ?? '')
        break
      case 'started':
        onStarted?.()
        break
      case 'output':
      case 'stdout':
        onOutput?.(msg.data ?? msg.text ?? '')
        break
      case 'error':
      case 'stderr':
        onError?.(msg.message ?? msg.data ?? msg.text ?? '')
        break
      case 'variable':
        onVariable?.(msg.name, msg.value)
        break
      case 'completed':
      case 'done':
      case 'finished':
        onCompleted?.(msg.variables ?? {})
        ws.close(1000)
        break
      default:
        break
    }
  }

  return {
    ws,
    cancel() {
      ws.close(1000)
    },
  }
}
