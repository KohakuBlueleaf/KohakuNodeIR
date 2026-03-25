/**
 * Unit tests for parserResultToGraph.
 *
 * Validates that viewer-format parser nodes/edges are correctly converted into
 * the graph store format (nodes with dataPorts/controlPorts, port IDs, etc.).
 */

import { describe, it, expect } from "vitest";
import { parserResultToGraph } from "../parserResultToGraph.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePortId(nodeId, portName, suffix) {
  const safe = portName.replace(/[^a-zA-Z0-9_]/g, "_");
  return `${nodeId}__${safe}__${suffix}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("parserResultToGraph", () => {
  it("returns { nodes, connections } shape", () => {
    const result = parserResultToGraph([], []);
    expect(result).toHaveProperty("nodes");
    expect(result).toHaveProperty("connections");
    expect(Array.isArray(result.nodes)).toBe(true);
    expect(Array.isArray(result.connections)).toBe(true);
  });

  // 1. Type inference: default value drives dataType when declared as 'any'
  it("infers 'int' dataType from integer default when port type is 'any'", () => {
    const parserNodes = [
      {
        id: "n1",
        type: "function",
        name: "myFunc",
        dataInputs: [{ name: "x", type: "any", default: 42 }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);

    const port = nodes[0].dataPorts.inputs[0];
    expect(port.dataType).toBe("int");
  });

  it("infers 'float' dataType from float default", () => {
    const parserNodes = [
      {
        id: "n2",
        type: "function",
        name: "f",
        dataInputs: [{ name: "rate", type: "any", default: 3.14 }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].dataPorts.inputs[0].dataType).toBe("float");
  });

  it("infers 'str' dataType from string default", () => {
    const parserNodes = [
      {
        id: "n3",
        type: "function",
        name: "f",
        dataInputs: [{ name: "label", type: "any", default: "hello" }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].dataPorts.inputs[0].dataType).toBe("str");
  });

  it("infers 'bool' dataType from boolean default", () => {
    const parserNodes = [
      {
        id: "n4",
        type: "function",
        name: "f",
        dataInputs: [{ name: "flag", type: "any", default: true }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].dataPorts.inputs[0].dataType).toBe("bool");
  });

  it("keeps declared type when it is not 'any'", () => {
    const parserNodes = [
      {
        id: "n5",
        type: "function",
        name: "f",
        dataInputs: [{ name: "x", type: "float", default: 0 }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    // Declared type is 'float' even though default is integer 0
    expect(nodes[0].dataPorts.inputs[0].dataType).toBe("float");
  });

  it("keeps 'any' type when default is null/undefined", () => {
    const parserNodes = [
      {
        id: "n6",
        type: "function",
        name: "f",
        dataInputs: [{ name: "x", type: "any" }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].dataPorts.inputs[0].dataType).toBe("any");
  });

  // 2. Value node properties
  it("value node with integer property value gets correct properties", () => {
    const parserNodes = [
      {
        id: "vn1",
        type: "value",
        name: "counter",
        properties: { value: 0 },
        dataInputs: [],
        dataOutputs: [{ name: "value", type: "int" }],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    expect(node.properties.value).toBe(0);
    expect(node.properties.valueType).toBe("int");
  });

  it("value node with string property gets valueType 'str'", () => {
    const parserNodes = [
      {
        id: "vn2",
        type: "value",
        name: "greeting",
        properties: { value: "hello" },
        dataInputs: [],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].properties.valueType).toBe("str");
    expect(nodes[0].properties.value).toBe("hello");
  });

  it("value node with no properties.value gets value=null", () => {
    const parserNodes = [
      {
        id: "vn3",
        type: "value",
        name: "empty",
        dataInputs: [],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].properties.value).toBeNull();
  });

  // 3. Port ID generation: deterministic, unique, correct format
  it("port IDs follow 'nodeId__portName__suffix' format", () => {
    const parserNodes = [
      {
        id: "fn1",
        type: "function",
        name: "f",
        dataInputs: [{ name: "a", type: "int" }],
        dataOutputs: [{ name: "result", type: "int" }],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    expect(node.dataPorts.inputs[0].id).toBe("fn1__a__di");
    expect(node.dataPorts.outputs[0].id).toBe("fn1__result__do");
  });

  it("port IDs are deterministic (same input → same output)", () => {
    const parserNodes = [
      {
        id: "det1",
        type: "function",
        name: "f",
        dataInputs: [{ name: "x", type: "any" }],
        dataOutputs: [],
      },
    ];

    const { nodes: nodes1 } = parserResultToGraph(parserNodes, []);
    const { nodes: nodes2 } = parserResultToGraph(parserNodes, []);

    expect(nodes1[0].dataPorts.inputs[0].id).toBe(
      nodes2[0].dataPorts.inputs[0].id,
    );
  });

  it("port IDs are unique across different ports on the same node", () => {
    const parserNodes = [
      {
        id: "uniq1",
        type: "function",
        name: "f",
        dataInputs: [
          { name: "a", type: "int" },
          { name: "b", type: "int" },
          { name: "c", type: "int" },
        ],
        dataOutputs: [{ name: "out", type: "int" }],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const allIds = [
      ...nodes[0].dataPorts.inputs.map((p) => p.id),
      ...nodes[0].dataPorts.outputs.map((p) => p.id),
    ];

    const unique = new Set(allIds);
    expect(unique.size).toBe(allIds.length);
  });

  it("control port IDs follow 'nodeId__portName__ci/co' format", () => {
    const parserNodes = [
      {
        id: "cp1",
        type: "function",
        name: "f",
        dataInputs: [],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    // Default ctrl ports are injected for non-value/non-load nodes
    expect(node.controlPorts.inputs[0].id).toBe("cp1__in__ci");
    expect(node.controlPorts.outputs[0].id).toBe("cp1__out__co");
  });

  // 4. Ctrl port defaults
  it("non-value, non-load nodes get default ctrl ports ['in'] / ['out']", () => {
    const parserNodes = [
      {
        id: "df1",
        type: "function",
        name: "doSomething",
        dataInputs: [],
        dataOutputs: [],
        // No ctrlInputs/ctrlOutputs provided
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    expect(node.controlPorts.inputs).toHaveLength(1);
    expect(node.controlPorts.inputs[0].name).toBe("in");

    expect(node.controlPorts.outputs).toHaveLength(1);
    expect(node.controlPorts.outputs[0].name).toBe("out");
  });

  it("value nodes do NOT get default ctrl ports", () => {
    const parserNodes = [
      {
        id: "val1",
        type: "value",
        name: "myVal",
        properties: { value: 1 },
        dataInputs: [],
        dataOutputs: [{ name: "value", type: "int" }],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    expect(node.controlPorts.inputs).toHaveLength(0);
    expect(node.controlPorts.outputs).toHaveLength(0);
  });

  it("load nodes do NOT get default ctrl ports", () => {
    const parserNodes = [
      {
        id: "ld1",
        type: "load",
        name: "loadData",
        dataInputs: [],
        dataOutputs: [{ name: "data", type: "any" }],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    expect(node.controlPorts.inputs).toHaveLength(0);
    expect(node.controlPorts.outputs).toHaveLength(0);
  });

  it("explicit ctrlInputs/ctrlOutputs override the defaults", () => {
    const parserNodes = [
      {
        id: "br1",
        type: "branch",
        name: "branch",
        dataInputs: [],
        dataOutputs: [],
        ctrlInputs: ["in"],
        ctrlOutputs: ["true", "false"],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    expect(node.controlPorts.inputs).toHaveLength(1);
    expect(node.controlPorts.outputs).toHaveLength(2);
    expect(node.controlPorts.outputs[0].name).toBe("true");
    expect(node.controlPorts.outputs[1].name).toBe("false");
  });

  // 5. Edge / connection conversion
  it("data edge is converted to a connection with portType 'data'", () => {
    const parserNodes = [
      {
        id: "src",
        type: "value",
        name: "v",
        dataInputs: [],
        dataOutputs: [{ name: "out", type: "int" }],
      },
      {
        id: "dst",
        type: "function",
        name: "f",
        dataInputs: [{ name: "inp", type: "int" }],
        dataOutputs: [],
      },
    ];

    const parserEdges = [
      {
        fromNode: "src",
        fromPort: "out",
        toNode: "dst",
        toPort: "inp",
        type: "data",
      },
    ];

    const { connections } = parserResultToGraph(parserNodes, parserEdges);

    expect(connections).toHaveLength(1);
    expect(connections[0].portType).toBe("data");
    expect(connections[0].fromNodeId).toBe("src");
    expect(connections[0].toNodeId).toBe("dst");
    expect(connections[0].fromPortId).toBe("src__out__do");
    expect(connections[0].toPortId).toBe("dst__inp__di");
  });

  it("control edge is converted to a connection with portType 'control'", () => {
    const parserNodes = [
      {
        id: "a",
        type: "function",
        name: "f1",
        dataInputs: [],
        dataOutputs: [],
        ctrlInputs: ["in"],
        ctrlOutputs: ["out"],
      },
      {
        id: "b",
        type: "function",
        name: "f2",
        dataInputs: [],
        dataOutputs: [],
        ctrlInputs: ["in"],
        ctrlOutputs: ["out"],
      },
    ];

    const parserEdges = [
      { fromNode: "a", fromPort: "out", toNode: "b", toPort: "in", type: "control" },
    ];

    const { connections } = parserResultToGraph(parserNodes, parserEdges);

    expect(connections[0].portType).toBe("control");
    expect(connections[0].fromPortId).toBe("a__out__co");
    expect(connections[0].toPortId).toBe("b__in__ci");
  });

  // 6. Default value is preserved on port object
  it("default value is attached to the port as defaultValue", () => {
    const parserNodes = [
      {
        id: "dv1",
        type: "function",
        name: "f",
        dataInputs: [{ name: "x", type: "int", default: 7 }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].dataPorts.inputs[0].defaultValue).toBe(7);
  });

  it("ports without a default do not have defaultValue property", () => {
    const parserNodes = [
      {
        id: "nd1",
        type: "function",
        name: "f",
        dataInputs: [{ name: "x", type: "int" }],
        dataOutputs: [],
      },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    expect(nodes[0].dataPorts.inputs[0]).not.toHaveProperty("defaultValue");
  });

  // 7. Node geometry defaults
  it("missing x/y/width/height default to 0/0/160/120", () => {
    const parserNodes = [
      { id: "geo1", type: "function", name: "f", dataInputs: [], dataOutputs: [] },
    ];

    const { nodes } = parserResultToGraph(parserNodes, []);
    const node = nodes[0];

    expect(node.x).toBe(0);
    expect(node.y).toBe(0);
    expect(node.width).toBe(160);
    expect(node.height).toBe(120);
  });
});
