/**
 * Unit tests for the graphToIr compiler.
 *
 * Exercises the compileGraph function directly with hand-constructed graph
 * objects — no Vue store, no component mounting required.
 */

import { describe, it, expect } from "vitest";
import { compileGraph } from "../graphToIr.js";

// ---------------------------------------------------------------------------
// Graph-builder helpers
// ---------------------------------------------------------------------------

function makeValueNode(id, name, value, valueType = "int") {
  return {
    id,
    type: "value",
    name,
    x: 0,
    y: 0,
    width: 160,
    height: 120,
    dataPorts: {
      inputs: [],
      outputs: [{ id: `${id}__value__do`, name: "value", dataType: valueType }],
    },
    controlPorts: { inputs: [], outputs: [] },
    properties: { value, valueType },
  };
}

function makeFunctionNode(id, funcType, inputDefs, outputDefs) {
  return {
    id,
    type: funcType,
    name: funcType,
    x: 0,
    y: 100,
    width: 160,
    height: 120,
    dataPorts: {
      inputs: inputDefs.map((p) => ({
        id: `${id}__${p.name}__di`,
        name: p.name,
        dataType: p.dataType ?? "any",
        ...(p.defaultValue !== undefined
          ? { defaultValue: p.defaultValue }
          : {}),
      })),
      outputs: outputDefs.map((p) => ({
        id: `${id}__${p.name}__do`,
        name: p.name,
        dataType: p.dataType ?? "any",
      })),
    },
    controlPorts: {
      inputs: [{ id: `${id}__in__ci`, name: "in" }],
      outputs: [{ id: `${id}__out__co`, name: "out" }],
    },
    properties: {},
  };
}

function makeBranchNode(id) {
  return {
    id,
    type: "branch",
    name: "branch",
    x: 0,
    y: 200,
    width: 160,
    height: 120,
    dataPorts: {
      inputs: [{ id: `${id}__cond__di`, name: "cond", dataType: "bool" }],
      outputs: [],
    },
    controlPorts: {
      inputs: [{ id: `${id}__in__ci`, name: "in" }],
      outputs: [
        { id: `${id}__true__co`, name: "true" },
        { id: `${id}__false__co`, name: "false" },
      ],
    },
    properties: {},
  };
}

// Connection factories
function dataConn(fromNode, fromPort, toNode, toPort) {
  return {
    id: `conn-${fromNode}-${toNode}`,
    fromNodeId: fromNode,
    fromPortId: `${fromNode}__${fromPort}__do`,
    toNodeId: toNode,
    toPortId: `${toNode}__${toPort}__di`,
    portType: "data",
  };
}

function ctrlConn(fromNode, fromPort, toNode, toPort) {
  return {
    id: `ctrl-${fromNode}-${toNode}`,
    fromNodeId: fromNode,
    fromPortId: `${fromNode}__${fromPort}__co`,
    toNodeId: toNode,
    toPortId: `${toNode}__${toPort}__ci`,
    portType: "control",
  };
}

// ---------------------------------------------------------------------------
// Local mirror of the compiler's outputVarName logic (for building expected strings)
// ---------------------------------------------------------------------------

function shortId(nodeId) {
  return nodeId.replace(/^node-/, "").replace(/[^a-zA-Z0-9_]/g, "_");
}

function sanitizeIdent(name) {
  return name.replace(/[^a-zA-Z0-9_.]/g, "_").replace(/^(\d)/, "_$1");
}

function expectedVarName(node, portName) {
  if (
    node.type === "value" &&
    node.name &&
    node.name !== "Node" &&
    node.name !== "value"
  ) {
    return sanitizeIdent(node.name);
  }
  const clean = portName.replace(/[^a-zA-Z0-9_]/g, "_");
  return `v_${shortId(node.id)}_${clean}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("compileGraph — controlflow mode", () => {
  it("returns an object with ir (string) and errors (array)", () => {
    const { ir, errors } = compileGraph([], []);
    expect(typeof ir).toBe("string");
    expect(Array.isArray(errors)).toBe(true);
  });

  // 1. Simple chain: value → function chain
  it("value node emits 'varname = literal' assignment", () => {
    const valNode = makeValueNode("node-val1", "myX", 10, "int");

    const { ir } = compileGraph([valNode], []);

    // Value node name becomes var name when not 'Node'/'value'
    expect(ir).toContain("myX = 10");
  });

  it("function node emits '(inputs)funcname(outputs)' call", () => {
    const funcNode = makeFunctionNode(
      "node-fn1",
      "add",
      [{ name: "a" }, { name: "b" }],
      [{ name: "result" }],
    );

    const { ir } = compileGraph([funcNode], []);

    expect(ir).toContain("add(");
  });

  // 2. Variable names are consistent between producer and consumer
  it("connected data edge: consumer call uses producer variable name", () => {
    const valNode = makeValueNode("node-src", "myInput", 99, "int");
    const funcNode = makeFunctionNode(
      "node-sink",
      "display",
      [{ name: "val" }],
      [],
    );

    const nodes = [valNode, funcNode];
    const connections = [dataConn("node-src", "value", "node-sink", "val")];

    const { ir } = compileGraph(nodes, connections);

    // The producer variable (myInput) must appear as the argument
    expect(ir).toContain("myInput = 99");
    expect(ir).toContain("(myInput)display(");
  });

  // 3. No undefined variables in the output
  it("produces no literal 'undefined' token in the KIR", () => {
    const valNode = makeValueNode("node-v2", "myVal", 42, "int");
    const funcNode = makeFunctionNode(
      "node-f2",
      "to_string",
      [{ name: "x" }],
      [{ name: "s" }],
    );

    const { ir } = compileGraph(
      [valNode, funcNode],
      [dataConn("node-v2", "value", "node-f2", "x")],
    );

    expect(ir).not.toContain("undefined");
  });

  // 4. Branch pattern: emits branch call with backtick namespace labels
  it("branch node emits '(cond)branch(`trueNs`, `falseNs`)' pattern", () => {
    const condVal = makeValueNode("node-cond", "flag", true, "bool");
    const branchNode = makeBranchNode("node-br1");

    const connections = [
      {
        id: "conn-cond-br",
        fromNodeId: "node-cond",
        fromPortId: "node-cond__value__do",
        toNodeId: "node-br1",
        toPortId: "node-br1__cond__di",
        portType: "data",
      },
    ];

    const { ir } = compileGraph([condVal, branchNode], connections);

    // Must match: (someExpr)branch(`nsA`, `nsB`)
    expect(ir).toMatch(/\(.*\)branch\(`[^`]+`,\s*`[^`]+`\)/);

    // Both namespace arms must be defined (label followed by colon)
    const nsMatches = [...ir.matchAll(/`([^`]+)`/g)].map((m) => m[1]);
    expect(nsMatches.length).toBeGreaterThanOrEqual(2);
  });

  it("branch emits two arm namespace labels", () => {
    const condVal = makeValueNode("node-c2", "ok", false, "bool");
    const branchNode = makeBranchNode("node-br2");

    const connections = [
      {
        id: "c-c2-br2",
        fromNodeId: "node-c2",
        fromPortId: "node-c2__value__do",
        toNodeId: "node-br2",
        toPortId: "node-br2__cond__di",
        portType: "data",
      },
    ];

    const { ir } = compileGraph([condVal, branchNode], connections);

    // Count namespace definition lines (label:)
    const labelLines = ir
      .split("\n")
      .filter((l) => /^\s*\w+\s*:$/.test(l.trim()));
    expect(labelLines.length).toBeGreaterThanOrEqual(2);
  });

  // 5. Variable naming collision: two nodes with port "result" get different var names
  it("two nodes with identical port names produce different variable names", () => {
    const func1 = makeFunctionNode(
      "node-fn1",
      "add",
      [{ name: "a" }, { name: "b" }],
      [{ name: "result" }],
    );
    const func2 = makeFunctionNode(
      "node-fn2",
      "multiply",
      [{ name: "a" }, { name: "b" }],
      [{ name: "result" }],
    );

    const var1 = expectedVarName(func1, "result"); // v_fn1_result
    const var2 = expectedVarName(func2, "result"); // v_fn2_result

    expect(var1).not.toBe(var2);

    const { ir } = compileGraph([func1, func2], []);

    expect(ir).toContain(var1);
    expect(ir).toContain(var2);
  });

  // 6. Value node with properties: emits actual value, not None
  it("value node integer property emits the integer literal", () => {
    const valNode = makeValueNode("node-lit", "counter", 42, "int");

    const { ir } = compileGraph([valNode], []);

    expect(ir).toContain("counter = 42");
    expect(ir).not.toContain("counter = None");
  });

  it("value node float property emits float literal", () => {
    const { ir } = compileGraph(
      [makeValueNode("node-flt", "rate", 3.14, "float")],
      [],
    );
    expect(ir).toContain("rate = 3.14");
  });

  it("value node string property emits quoted string literal", () => {
    const { ir } = compileGraph(
      [makeValueNode("node-str", "greeting", "hello", "str")],
      [],
    );
    expect(ir).toContain('greeting = "hello"');
  });

  it("value node bool true property emits True", () => {
    const { ir } = compileGraph(
      [makeValueNode("node-bool", "flag", true, "bool")],
      [],
    );
    expect(ir).toContain("flag = True");
  });

  // 7. Literal defaults on function inputs
  it("unconnected input with default value uses the literal in the call", () => {
    const toFloatNode = {
      id: "node-tofloat",
      type: "to_float",
      name: "to_float",
      x: 0,
      y: 0,
      width: 160,
      height: 120,
      dataPorts: {
        inputs: [
          {
            id: "node-tofloat__x__di",
            name: "x",
            dataType: "int",
            defaultValue: 10,
          },
        ],
        outputs: [
          { id: "node-tofloat__result__do", name: "result", dataType: "float" },
        ],
      },
      controlPorts: {
        inputs: [{ id: "node-tofloat__in__ci", name: "in" }],
        outputs: [{ id: "node-tofloat__out__co", name: "out" }],
      },
      properties: {},
    };

    const { ir } = compileGraph([toFloatNode], []);

    expect(ir).toContain("(10)to_float(");
  });

  // 8. Value node with generic name "Node" falls back to v_... pattern
  it("value node named 'Node' uses the v_... variable name pattern", () => {
    const valNode = makeValueNode("node-generic", "Node", 5, "int");

    const { ir } = compileGraph([valNode], []);

    expect(ir).not.toContain("Node = 5");
    expect(ir).toContain("v_generic_value = 5");
  });

  // 9. Unconnected function input with no default falls back to None
  it("unconnected input with no default emits None", () => {
    const funcNode = makeFunctionNode(
      "node-nodefault",
      "process",
      [{ name: "x" }],
      [{ name: "y" }],
    );

    const { ir } = compileGraph([funcNode], []);

    expect(ir).toContain("(None)process(");
  });

  // 10. Multiple value nodes all appear in output
  it("multiple value nodes are all emitted", () => {
    const v1 = makeValueNode("node-a", "alpha", 1, "int");
    const v2 = makeValueNode("node-b", "beta", 2, "int");
    const v3 = makeValueNode("node-c", "gamma", 3, "int");

    const { ir } = compileGraph([v1, v2, v3], []);

    expect(ir).toContain("alpha = 1");
    expect(ir).toContain("beta = 2");
    expect(ir).toContain("gamma = 3");
  });

  // 11. Empty graph returns comment string
  it("empty graph returns non-empty string without errors", () => {
    const { ir, errors } = compileGraph([], []);
    expect(ir.length).toBeGreaterThan(0);
    expect(errors).toHaveLength(0);
  });

  // 12. ctrl chain: value → add → print — function names appear in KIR
  it("ctrl-chained nodes all appear in the KIR", () => {
    const valNode = makeValueNode("node-v3", "n", 7, "int");
    const addNode = makeFunctionNode(
      "node-add3",
      "add",
      [{ name: "a" }, { name: "b" }],
      [{ name: "result" }],
    );
    const printNode = makeFunctionNode(
      "node-print3",
      "print",
      [{ name: "value" }],
      [],
    );

    const nodes = [valNode, addNode, printNode];
    const connections = [
      dataConn("node-v3", "value", "node-add3", "a"),
      ctrlConn("node-add3", "out", "node-print3", "in"),
    ];

    const { ir } = compileGraph(nodes, connections);

    expect(ir).toContain("n = 7");
    expect(ir).toContain("add(");
    expect(ir).toContain("print(");
  });
});

describe("compileGraph — dataflow mode", () => {
  it("dataflow mode header contains '@mode dataflow'", () => {
    const { ir } = compileGraph([], [], "dataflow");
    expect(ir).toContain("@mode dataflow");
  });

  it("value node in dataflow mode still emits assignment", () => {
    const valNode = makeValueNode("node-dv1", "speed", 60, "int");
    const { ir } = compileGraph([valNode], [], "dataflow");
    expect(ir).toContain("speed = 60");
  });

  it("function node in dataflow mode emits call with resolved inputs", () => {
    const valNode = makeValueNode("node-dv2", "x", 5, "int");
    const funcNode = makeFunctionNode(
      "node-df2",
      "square",
      [{ name: "n" }],
      [{ name: "out" }],
    );

    const { ir } = compileGraph(
      [valNode, funcNode],
      [dataConn("node-dv2", "value", "node-df2", "n")],
      "dataflow",
    );

    expect(ir).toContain("(x)square(");
  });
});
