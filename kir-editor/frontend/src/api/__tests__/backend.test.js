/**
 * Unit tests for backend.js API helpers.
 *
 * fetch and WebSocket are mocked so no real network calls are made.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Minimal WebSocket mock (created fresh for each test)
// ---------------------------------------------------------------------------

class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.sentMessages = [];
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    MockWebSocket.lastInstance = this;
  }

  send(data) {
    this.sentMessages.push(data);
  }

  close(code) {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  // Test helper: trigger onopen
  triggerOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  // Test helper: trigger onmessage
  triggerMessage(data) {
    this.onmessage?.({
      data: typeof data === "string" ? data : JSON.stringify(data),
    });
  }
}

MockWebSocket.lastInstance = null;

// ---------------------------------------------------------------------------
// Mock window.location (used by _wsUrl)
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("window", {
    location: {
      protocol: "http:",
      host: "localhost:5174",
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Import module under test AFTER mocks are set up.
// Using dynamic import so the module is re-evaluated after globals are patched.
// ---------------------------------------------------------------------------

async function getBackend() {
  // Use cache-busted import in case vitest caches the module
  return import("../backend.js");
}

// ---------------------------------------------------------------------------
// executeKirStreaming — WebSocket message sending
// ---------------------------------------------------------------------------

describe("executeKirStreaming", () => {
  it("opens a WebSocket to /api/ws/execute path", async () => {
    const { executeKirStreaming } = await getBackend();
    executeKirStreaming("x = 1", {});

    const ws = MockWebSocket.lastInstance;
    expect(ws.url).toContain("/api/ws/execute");
  });

  it("sends { type: 'execute', kir_source } when socket opens", async () => {
    const { executeKirStreaming } = await getBackend();
    const kirSource = "x = 42\n()print(x)";

    executeKirStreaming(kirSource, {});

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();

    expect(ws.sentMessages).toHaveLength(1);
    const sent = JSON.parse(ws.sentMessages[0]);
    expect(sent.type).toBe("execute");
    expect(sent.kir_source).toBe(kirSource);
  });

  it("calls onOutput with msg.value on 'output' message", async () => {
    const { executeKirStreaming } = await getBackend();
    const received = [];

    executeKirStreaming("x = 1", { onOutput: (v) => received.push(v) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "output", value: "hello" });

    expect(received).toEqual(["hello"]);
  });

  it("calls onOutput with msg.data when msg.value is absent", async () => {
    const { executeKirStreaming } = await getBackend();
    const received = [];

    executeKirStreaming("x = 1", { onOutput: (v) => received.push(v) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "output", data: "world" });

    expect(received).toEqual(["world"]);
  });

  it("'stdout' message type also calls onOutput", async () => {
    const { executeKirStreaming } = await getBackend();
    const received = [];

    executeKirStreaming("x = 1", { onOutput: (v) => received.push(v) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "stdout", value: "line1" });

    expect(received).toEqual(["line1"]);
  });

  it("calls onError on 'error' message with msg.message", async () => {
    const { executeKirStreaming } = await getBackend();
    const errs = [];

    executeKirStreaming("bad code", { onError: (m) => errs.push(m) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "error", message: "SyntaxError: oops" });

    expect(errs).toEqual(["SyntaxError: oops"]);
  });

  it("calls onStarted on 'started' message", async () => {
    const { executeKirStreaming } = await getBackend();
    let started = false;

    executeKirStreaming("x = 1", { onStarted: () => (started = true) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "started" });

    expect(started).toBe(true);
  });

  it("calls onVariable on 'variable' message with name and value", async () => {
    const { executeKirStreaming } = await getBackend();
    const vars = [];

    executeKirStreaming("x = 1", { onVariable: (n, v) => vars.push({ n, v }) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "variable", name: "x", value: 42 });

    expect(vars).toEqual([{ n: "x", v: 42 }]);
  });

  it("calls onCompleted with variables and closes socket on 'completed'", async () => {
    const { executeKirStreaming } = await getBackend();
    let completedVars = null;

    executeKirStreaming("x = 1", { onCompleted: (v) => (completedVars = v) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "completed", variables: { x: 1 } });

    expect(completedVars).toEqual({ x: 1 });
    expect(ws.readyState).toBe(3); // closed
  });

  it("'done' message type also triggers onCompleted", async () => {
    const { executeKirStreaming } = await getBackend();
    let completedVars = null;

    executeKirStreaming("x = 1", { onCompleted: (v) => (completedVars = v) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "done" });

    expect(completedVars).toEqual({});
  });

  it("cancel() closes the WebSocket", async () => {
    const { executeKirStreaming } = await getBackend();
    const { cancel } = executeKirStreaming("x = 1", {});

    const ws = MockWebSocket.lastInstance;
    cancel();

    expect(ws.readyState).toBe(3);
  });

  it("returns { ws, cancel } object", async () => {
    const { executeKirStreaming } = await getBackend();
    const result = executeKirStreaming("x = 1", {});

    expect(result).toHaveProperty("ws");
    expect(result).toHaveProperty("cancel");
    expect(typeof result.cancel).toBe("function");
  });

  it("raw non-JSON message calls onOutput with the raw string", async () => {
    const { executeKirStreaming } = await getBackend();
    const received = [];

    executeKirStreaming("x = 1", { onOutput: (v) => received.push(v) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    // Simulate a non-JSON message
    ws.onmessage?.({ data: "plain text line" });

    expect(received).toEqual(["plain text line"]);
  });

  it("unknown message type is silently ignored", async () => {
    const { executeKirStreaming } = await getBackend();
    const received = [];
    const errs = [];

    executeKirStreaming("x = 1", {
      onOutput: (v) => received.push(v),
      onError: (e) => errs.push(e),
    });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "unknown_type", data: "ignored" });

    expect(received).toHaveLength(0);
    expect(errs).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// executeKirgraphStreaming — similar but sends a kirgraph object
// ---------------------------------------------------------------------------

describe("executeKirgraphStreaming", () => {
  it("opens WebSocket to /api/ws/execute/kirgraph", async () => {
    const { executeKirgraphStreaming } = await getBackend();
    executeKirgraphStreaming({ nodes: [], connections: [] }, {});

    const ws = MockWebSocket.lastInstance;
    expect(ws.url).toContain("/api/ws/execute/kirgraph");
  });

  it("sends { type: 'execute', kirgraph } on open", async () => {
    const { executeKirgraphStreaming } = await getBackend();
    const kg = { nodes: [{ id: "n1" }], connections: [] };

    executeKirgraphStreaming(kg, {});

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();

    const sent = JSON.parse(ws.sentMessages[0]);
    expect(sent.type).toBe("execute");
    expect(sent.kirgraph).toEqual(kg);
  });

  it("calls onCompiled with kir_source on 'compiled' message", async () => {
    const { executeKirgraphStreaming } = await getBackend();
    let compiledSrc = null;

    executeKirgraphStreaming({}, { onCompiled: (s) => (compiledSrc = s) });

    const ws = MockWebSocket.lastInstance;
    ws.triggerOpen();
    ws.triggerMessage({ type: "compiled", kir_source: "x = 1\n" });

    expect(compiledSrc).toBe("x = 1\n");
  });
});

// ---------------------------------------------------------------------------
// REST helpers — executeKir, listNodes
// ---------------------------------------------------------------------------

describe("executeKir (REST)", () => {
  it("POSTs to /api/execute with kir_source in body", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, output: "42" }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { executeKir } = await getBackend();
    await executeKir("x = 42");

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/execute");
    expect(opts.method).toBe("POST");

    const body = JSON.parse(opts.body);
    expect(body.kir_source).toBe("x = 42");
  });

  it("throws on non-ok response", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => ({ detail: "Execution failed" }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { executeKir } = await getBackend();
    await expect(executeKir("bad")).rejects.toThrow("Execution failed");
  });
});

describe("listNodes (REST)", () => {
  it("GETs /api/nodes and returns the parsed JSON", async () => {
    const mockNodes = [{ name: "add", type: "add" }];
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockNodes,
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { listNodes } = await getBackend();
    const result = await listNodes();

    expect(fetchSpy).toHaveBeenCalledWith("/api/nodes");
    expect(result).toEqual(mockNodes);
  });
});
