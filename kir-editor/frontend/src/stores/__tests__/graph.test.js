/**
 * Unit tests for the graph Pinia store.
 *
 * Uses createPinia + setActivePinia so each test gets a fresh store instance.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useGraphStore } from "../graph.js";
import { useHistoryStore } from "../history.js";

// The history store calls useGraphStore().serialize() — we need a pinia
// instance set up before any store is used.
beforeEach(() => {
  setActivePinia(createPinia());
});

// ---------------------------------------------------------------------------
// Node data builders
// ---------------------------------------------------------------------------

function makeNode(overrides = {}) {
  return {
    type: "function",
    name: "TestNode",
    x: 0,
    y: 0,
    width: 160,
    height: 120,
    dataPorts: {
      inputs: [{ id: "p-in", name: "a", dataType: "int" }],
      outputs: [{ id: "p-out", name: "result", dataType: "int" }],
    },
    controlPorts: {
      inputs: [{ id: "p-ci", name: "in" }],
      outputs: [{ id: "p-co", name: "out" }],
    },
    properties: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// addNode / removeNode
// ---------------------------------------------------------------------------

describe("addNode", () => {
  it("adds the node and returns a string id", () => {
    const graph = useGraphStore();
    const id = graph.addNode(makeNode());

    expect(typeof id).toBe("string");
    expect(graph.nodes.has(id)).toBe(true);
  });

  it("stores all the node fields", () => {
    const graph = useGraphStore();
    const id = graph.addNode(makeNode({ name: "MyFunc", type: "my_func" }));
    const node = graph.nodes.get(id);

    expect(node.name).toBe("MyFunc");
    expect(node.type).toBe("my_func");
  });

  it("uses provided id when given", () => {
    const graph = useGraphStore();
    const id = graph.addNode(makeNode({ id: "custom-id-123" }));
    expect(id).toBe("custom-id-123");
    expect(graph.nodes.has("custom-id-123")).toBe(true);
  });

  it("snaps x/y to grid (multiples of 20)", () => {
    const graph = useGraphStore();
    const id = graph.addNode(makeNode({ x: 13, y: 27 }));
    const node = graph.nodes.get(id);
    expect(node.x % 20).toBe(0);
    expect(node.y % 20).toBe(0);
  });

  it("nodeList computed includes the new node", () => {
    const graph = useGraphStore();
    const id = graph.addNode(makeNode());
    expect(graph.nodeList.some((n) => n.id === id)).toBe(true);
  });
});

describe("removeNode", () => {
  it("removes the node from the map", () => {
    const graph = useGraphStore();
    const id = graph.addNode(makeNode());
    graph.removeNode(id);
    expect(graph.nodes.has(id)).toBe(false);
  });

  it("does nothing when node id does not exist", () => {
    const graph = useGraphStore();
    // Should not throw
    expect(() => graph.removeNode("nonexistent")).not.toThrow();
  });

  it("cascades — removes connections that reference the deleted node", () => {
    const graph = useGraphStore();

    const idA = graph.addNode({
      type: "function",
      name: "A",
      x: 0,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [],
        outputs: [{ id: "A-out", name: "r", dataType: "int" }],
      },
      controlPorts: { inputs: [], outputs: [] },
      properties: {},
    });

    const idB = graph.addNode({
      type: "function",
      name: "B",
      x: 200,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [{ id: "B-in", name: "x", dataType: "int" }],
        outputs: [],
      },
      controlPorts: { inputs: [], outputs: [] },
      properties: {},
    });

    const connId = graph.addConnection(idA, "A-out", idB, "B-in", "data");
    expect(connId).not.toBeNull();

    graph.removeNode(idA);

    expect(graph.connections.has(connId)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// addConnection / canConnect
// ---------------------------------------------------------------------------

describe("addConnection", () => {
  function setupTwoNodes() {
    const graph = useGraphStore();

    const idA = graph.addNode({
      id: "node-A",
      type: "function",
      name: "A",
      x: 0,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [],
        outputs: [{ id: "A-do", name: "out", dataType: "int" }],
      },
      controlPorts: {
        inputs: [],
        outputs: [{ id: "A-co", name: "out" }],
      },
      properties: {},
    });

    const idB = graph.addNode({
      id: "node-B",
      type: "function",
      name: "B",
      x: 200,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [{ id: "B-di", name: "in", dataType: "int" }],
        outputs: [],
      },
      controlPorts: {
        inputs: [{ id: "B-ci", name: "in" }],
        outputs: [],
      },
      properties: {},
    });

    return { graph, idA, idB };
  }

  it("adds a valid data connection and returns a string id", () => {
    const { graph, idA, idB } = setupTwoNodes();
    const connId = graph.addConnection(idA, "A-do", idB, "B-di", "data");

    expect(typeof connId).toBe("string");
    expect(graph.connections.has(connId)).toBe(true);
  });

  it("self-loop is rejected (returns null)", () => {
    const { graph, idA } = setupTwoNodes();
    const result = graph.addConnection(idA, "A-do", idA, "B-di", "data");
    expect(result).toBeNull();
  });

  it("duplicate connection is rejected (returns null)", () => {
    const { graph, idA, idB } = setupTwoNodes();
    graph.addConnection(idA, "A-do", idB, "B-di", "data");
    const second = graph.addConnection(idA, "A-do", idB, "B-di", "data");
    expect(second).toBeNull();
  });

  it("invalid portType is rejected", () => {
    const { graph, idA, idB } = setupTwoNodes();
    const result = graph.addConnection(idA, "A-do", idB, "B-di", "unknown");
    expect(result).toBeNull();
  });

  it("data connection to ctrl port is rejected (wrong port direction)", () => {
    const { graph, idA, idB } = setupTwoNodes();
    // Trying to connect A's data output to B's ctrl input — ports don't exist on the right lists
    const result = graph.addConnection(idA, "A-do", idB, "B-ci", "data");
    expect(result).toBeNull();
  });

  it("ctrl connection works when ports exist on both nodes", () => {
    const { graph, idA, idB } = setupTwoNodes();
    const connId = graph.addConnection(idA, "A-co", idB, "B-ci", "control");
    expect(connId).not.toBeNull();
    expect(graph.connections.get(connId).portType).toBe("control");
  });

  it("connectionList computed includes new connection", () => {
    const { graph, idA, idB } = setupTwoNodes();
    const connId = graph.addConnection(idA, "A-do", idB, "B-di", "data");
    expect(graph.connectionList.some((c) => c.id === connId)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// removeConnection
// ---------------------------------------------------------------------------

describe("removeConnection", () => {
  it("removes the connection from the map", () => {
    const graph = useGraphStore();

    const idA = graph.addNode({
      id: "rA",
      type: "function",
      name: "A",
      x: 0,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [],
        outputs: [{ id: "rA-do", name: "out", dataType: "int" }],
      },
      controlPorts: { inputs: [], outputs: [] },
      properties: {},
    });
    const idB = graph.addNode({
      id: "rB",
      type: "function",
      name: "B",
      x: 200,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [{ id: "rB-di", name: "in", dataType: "int" }],
        outputs: [],
      },
      controlPorts: { inputs: [], outputs: [] },
      properties: {},
    });

    const connId = graph.addConnection(idA, "rA-do", idB, "rB-di", "data");
    graph.removeConnection(connId);
    expect(graph.connections.has(connId)).toBe(false);
  });

  it("does nothing (no throw) when connection id does not exist", () => {
    const graph = useGraphStore();

    const sizeBefore = graph.connections.size;
    // Should not throw
    expect(() => graph.removeConnection("nonexistent-conn-id")).not.toThrow();
    expect(graph.connections.size).toBe(sizeBefore);
  });

  it("non-existent removeConnection does NOT push history", () => {
    // History pushState increments undoStack; verify it stays unchanged when
    // removing a connection id that doesn't exist.
    const graph = useGraphStore();
    const history = useHistoryStore();

    const stackLenBefore = history.undoStack.length;
    graph.removeConnection("no-such-id");
    const stackLenAfter = history.undoStack.length;

    expect(stackLenAfter).toBe(stackLenBefore);
  });
});

// ---------------------------------------------------------------------------
// getPortPosition
// ---------------------------------------------------------------------------

describe("getPortPosition", () => {
  it("returns null for unknown node id", () => {
    const graph = useGraphStore();
    expect(graph.getPortPosition("no-node", "no-port")).toBeNull();
  });

  it("data input port is on the left edge (x === node.x)", () => {
    const graph = useGraphStore();

    const id = graph.addNode({
      id: "pos-node",
      type: "function",
      name: "F",
      x: 100,
      y: 200,
      width: 160,
      height: 200,
      dataPorts: {
        inputs: [{ id: "pos-di", name: "a", dataType: "int" }],
        outputs: [],
      },
      controlPorts: {
        inputs: [{ id: "pos-ci", name: "in" }],
        outputs: [{ id: "pos-co", name: "out" }],
      },
      properties: {},
    });

    const pos = graph.getPortPosition(id, "pos-di");
    expect(pos).not.toBeNull();
    expect(pos.x).toBe(100); // left edge of node
  });

  it("data output port is on the right edge (x === node.x + node.width)", () => {
    const graph = useGraphStore();

    const id = graph.addNode({
      id: "pos-node2",
      type: "function",
      name: "F",
      x: 100,
      y: 200,
      width: 160,
      height: 200,
      dataPorts: {
        inputs: [],
        outputs: [{ id: "pos-do", name: "r", dataType: "int" }],
      },
      controlPorts: { inputs: [], outputs: [] },
      properties: {},
    });

    const node = graph.nodes.get(id);
    const pos = graph.getPortPosition(id, "pos-do");

    expect(pos).not.toBeNull();
    expect(pos.x).toBe(node.x + node.width);
  });

  it("ctrl output Y uses effective height (>= computeMinHeight)", () => {
    const graph = useGraphStore();

    // Node with many data ports — store height is deliberately too small
    const dataInputs = Array.from({ length: 5 }, (_, i) => ({
      id: `pci-di-${i}`,
      name: `a${i}`,
      dataType: "int",
    }));

    const id = graph.addNode({
      id: "eff-height-node",
      type: "function",
      name: "F",
      x: 0,
      y: 0,
      width: 160,
      height: 80, // deliberately smaller than needed
      dataPorts: {
        inputs: dataInputs,
        outputs: [],
      },
      controlPorts: {
        inputs: [{ id: "eff-ci", name: "in" }],
        outputs: [{ id: "eff-co", name: "out" }],
      },
      properties: {},
    });

    const node = graph.nodes.get(id);
    const pos = graph.getPortPosition(id, "eff-co");

    // CTRL_ROW_H = 18, so pos.y should be effective_height - 9
    // The effective height must be >= computeMinHeight (which, with 5 data inputs,
    // is larger than the stored 80px).
    // Raw: y + 80 - 9 = 71.  Effective: y + minHeight - 9 which is > 71.
    const rawY = node.y + node.height - 9;
    expect(pos.y).toBeGreaterThan(rawY);
  });

  it("ctrl input port Y is near the top of the node", () => {
    const graph = useGraphStore();

    const id = graph.addNode({
      id: "top-ctrl-node",
      type: "function",
      name: "F",
      x: 50,
      y: 100,
      width: 160,
      height: 120,
      dataPorts: { inputs: [], outputs: [] },
      controlPorts: {
        inputs: [{ id: "top-ci", name: "in" }],
        outputs: [],
      },
      properties: {},
    });

    const node = graph.nodes.get(id);
    const pos = graph.getPortPosition(id, "top-ci");

    // CTRL_ROW_H = 18, port is at midpoint = 9px below node top
    expect(pos).not.toBeNull();
    expect(pos.y).toBe(node.y + 9); // CTRL_ROW_H / 2 = 9
  });
});

// ---------------------------------------------------------------------------
// clear / serialize / deserialize
// ---------------------------------------------------------------------------

describe("clear", () => {
  it("removes all nodes and connections", () => {
    const graph = useGraphStore();

    graph.addNode(makeNode({ id: "cl-1" }));
    graph.addNode(makeNode({ id: "cl-2" }));
    graph.clear();

    expect(graph.nodes.size).toBe(0);
    expect(graph.connections.size).toBe(0);
  });
});

describe("serialize / deserialize", () => {
  it("round-trips the graph state through JSON", () => {
    const graph = useGraphStore();

    const id = graph.addNode(makeNode({ id: "rt-node", name: "RoundTrip" }));
    const snapshot = graph.serialize();

    graph.clear();
    expect(graph.nodes.size).toBe(0);

    graph.deserialize(snapshot);
    expect(graph.nodes.has(id)).toBe(true);
    expect(graph.nodes.get(id).name).toBe("RoundTrip");
  });

  it("serialize returns plain objects (no Map/reactive proxies)", () => {
    const graph = useGraphStore();
    graph.addNode(makeNode({ id: "ser-1" }));

    const snap = graph.serialize();
    expect(Array.isArray(snap.nodes)).toBe(true);
    expect(Array.isArray(snap.connections)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// getNodeConnections / getPortConnections
// ---------------------------------------------------------------------------

describe("getNodeConnections", () => {
  it("returns all connections touching a given node", () => {
    const graph = useGraphStore();

    const idA = graph.addNode({
      id: "gc-A",
      type: "function",
      name: "A",
      x: 0,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [],
        outputs: [{ id: "gcA-do", name: "out", dataType: "int" }],
      },
      controlPorts: { inputs: [], outputs: [] },
      properties: {},
    });
    const idB = graph.addNode({
      id: "gc-B",
      type: "function",
      name: "B",
      x: 200,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [{ id: "gcB-di", name: "in", dataType: "int" }],
        outputs: [],
      },
      controlPorts: { inputs: [], outputs: [] },
      properties: {},
    });

    graph.addConnection(idA, "gcA-do", idB, "gcB-di", "data");

    const conns = graph.getNodeConnections(idA);
    expect(conns).toHaveLength(1);
    expect(conns[0].fromNodeId).toBe(idA);
  });

  it("returns empty array for a node with no connections", () => {
    const graph = useGraphStore();
    const id = graph.addNode(makeNode({ id: "iso-node" }));
    expect(graph.getNodeConnections(id)).toHaveLength(0);
  });
});
