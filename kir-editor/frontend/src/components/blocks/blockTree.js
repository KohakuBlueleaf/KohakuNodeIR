import { ref, watch } from "vue";
import { compileGraph } from "../../compiler/graphToIr.js";
import {
  parseKirToAst,
  isWasmReady,
  initWasm,
} from "../../parser/wasmParser.js";

// ---------------------------------------------------------------------------
// AST → Block tree walker
// ---------------------------------------------------------------------------

/**
 * Serialize a KIR AST expression node to a display-friendly object.
 * These become { kind, text } for ReporterBlock to render.
 *
 * @param {object|null} expr  - serialized AST expression from Python
 * @returns {{ kind: string, text: string }}
 */
function serializeExpr(expr) {
  if (!expr) return { kind: "empty", text: "" };
  switch (expr.type) {
    case "Identifier":
      return { kind: "var", text: expr.name ?? "" };
    case "Literal":
      return { kind: "literal", text: String(expr.value ?? "") };
    case "KeywordArg":
      return {
        kind: "kwarg",
        text: `${expr.name}=${serializeExpr(expr.value).text}`,
      };
    case "LabelRef":
      return { kind: "label", text: expr.name ?? "" };
    case "Wildcard":
      return { kind: "wildcard", text: "_" };
    default:
      return { kind: "unknown", text: JSON.stringify(expr) };
  }
}

/**
 * Serialize a KIR output target (str | Wildcard) to a string.
 * @param {string|object} out
 * @returns {string}
 */
function serializeOutput(out) {
  if (!out) return "_";
  if (typeof out === "string") return out;
  if (out.type === "Wildcard") return "_";
  return String(out);
}

/**
 * Walk a list of AST statements and return an array of block objects.
 * Namespaces referenced by a Branch/Switch are inlined as arms rather than
 * independent blocks, so we first index namespaces by name.
 *
 * @param {object[]} stmts
 * @returns {object[]}
 */
function walkStatements(stmts) {
  if (!stmts || !stmts.length) return [];

  // Build a map of namespace name → namespace node for arm look-ups
  const nsMap = new Map();
  for (const stmt of stmts) {
    if (stmt.type === "Namespace") nsMap.set(stmt.name, stmt);
  }

  // Track which namespaces are used as branch/switch arms so we can skip
  // rendering them as standalone blocks
  const consumedNs = new Set();

  // First pass: find all label refs used in Branch / Switch / Parallel
  for (const stmt of stmts) {
    if (stmt.type === "Branch") {
      if (stmt.true_label) consumedNs.add(stmt.true_label);
      if (stmt.false_label) consumedNs.add(stmt.false_label);
    } else if (stmt.type === "Switch") {
      for (const [, label] of stmt.cases ?? []) consumedNs.add(label);
      if (stmt.default_label) consumedNs.add(stmt.default_label);
    } else if (stmt.type === "Parallel") {
      for (const label of stmt.labels ?? []) consumedNs.add(label);
    }
  }

  const blocks = [];

  for (const stmt of stmts) {
    // Skip namespaces that are already embedded in a control block arm
    if (stmt.type === "Namespace" && consumedNs.has(stmt.name)) continue;

    const block = stmtToBlock(stmt, nsMap);
    if (block) blocks.push(block);
  }

  return blocks;
}

/**
 * Convert a single AST statement to a block descriptor.
 *
 * @param {object} stmt
 * @param {Map<string,object>} nsMap  - sibling namespace map for arm look-up
 * @returns {object|null}
 */
function stmtToBlock(stmt, nsMap) {
  switch (stmt.type) {
    case "FuncCall":
      return {
        type: "statement",
        key: `fc-${stmt.line ?? Math.random()}`,
        funcName: stmt.func_name ?? "?",
        inputs: (stmt.inputs ?? []).map(serializeExpr),
        outputs: (stmt.outputs ?? []).map(serializeOutput),
      };

    case "Assignment":
      return {
        type: "assignment",
        key: `assign-${stmt.line ?? Math.random()}`,
        target: stmt.target ?? "_",
        value: serializeExpr(stmt.value),
      };

    case "Branch": {
      const trueNs = nsMap.get(stmt.true_label);
      const falseNs = nsMap.get(stmt.false_label);
      return {
        type: "branch",
        key: `branch-${stmt.line ?? Math.random()}`,
        condition: serializeExpr(stmt.condition),
        arms: [
          {
            label: stmt.true_label ?? "true",
            blocks: trueNs ? walkStatements(trueNs.body) : [],
          },
          {
            label: stmt.false_label ?? "false",
            blocks: falseNs ? walkStatements(falseNs.body) : [],
          },
        ],
      };
    }

    case "Switch": {
      const arms = (stmt.cases ?? []).map(([expr, label]) => ({
        label: label ?? "?",
        caseExpr: serializeExpr(expr),
        blocks: nsMap.get(label) ? walkStatements(nsMap.get(label).body) : [],
      }));
      if (stmt.default_label) {
        const defNs = nsMap.get(stmt.default_label);
        arms.push({
          label: stmt.default_label,
          caseExpr: { kind: "label", text: "default" },
          blocks: defNs ? walkStatements(defNs.body) : [],
        });
      }
      return {
        type: "switch",
        key: `switch-${stmt.line ?? Math.random()}`,
        value: serializeExpr(stmt.value),
        arms,
      };
    }

    case "Parallel": {
      const arms = (stmt.labels ?? []).map((label) => ({
        label,
        blocks: nsMap.get(label) ? walkStatements(nsMap.get(label).body) : [],
      }));
      return {
        type: "parallel",
        key: `par-${stmt.line ?? Math.random()}`,
        arms,
      };
    }

    case "Namespace":
      // Standalone namespace (not consumed as a branch arm)
      return {
        type: "namespace",
        key: `ns-${stmt.name}-${stmt.line ?? Math.random()}`,
        label: stmt.name ?? "",
        blocks: walkStatements(stmt.body ?? []),
      };

    case "DataflowBlock":
      return {
        type: "dataflow",
        key: `df-${stmt.line ?? Math.random()}`,
        blocks: walkStatements(stmt.body ?? []),
      };

    case "Jump":
      return {
        type: "jump",
        key: `jump-${stmt.line ?? Math.random()}`,
        target: stmt.target ?? "",
      };

    case "SubgraphDef":
      return {
        type: "subgraph",
        key: `def-${stmt.name}-${stmt.line ?? Math.random()}`,
        name: stmt.name ?? "",
        params: (stmt.params ?? []).map((p) => p.name ?? ""),
        outputs: stmt.outputs ?? [],
        blocks: walkStatements(stmt.body ?? []),
      };

    case "ModeDecl":
      return {
        type: "mode",
        key: `mode-${stmt.line ?? Math.random()}`,
        mode: stmt.mode ?? "",
      };

    default:
      return null;
  }
}

/**
 * Convert a parsed AST program (plain JS object from Pyodide JSON) to a
 * block tree ready for rendering.
 *
 * @param {object} program  - { type: 'Program', body: [...], mode: ... }
 * @returns {{ stacks: object[] }}
 */
function astToBlockTree(program) {
  if (!program || !program.body) return { stacks: [] };

  const allBlocks = walkStatements(program.body);

  // Split top-level blocks into stacks.
  // SubgraphDefs each get their own stack (separate column).
  // Everything else goes in one primary stack.
  const mainBlocks = [];
  const extraStacks = [];

  for (const block of allBlocks) {
    if (block.type === "subgraph") {
      extraStacks.push({ key: block.key, blocks: [block] });
    } else {
      mainBlocks.push(block);
    }
  }

  const stacks = [];
  if (mainBlocks.length) stacks.push({ key: "main", blocks: mainBlocks });
  stacks.push(...extraStacks);

  return { stacks };
}

// ---------------------------------------------------------------------------
// Public composable
// ---------------------------------------------------------------------------

/**
 * Reactive composable that derives a block tree from the KIR AST.
 *
 * The pipeline is:
 *   graph store → compileGraph() → KIR text → parseKirToAst() → AST → block tree
 *
 * The block tree is stored in a plain ref and is updated asynchronously
 * whenever the graph changes. While Pyodide is loading, the tree shows a
 * loading placeholder. If Pyodide fails entirely, a fallback KIR-text stack
 * is shown instead.
 *
 * @param {import('pinia').Store} graphStore
 * @returns {{ blockTree: import('vue').Ref, kirText: import('vue').Ref, wasmStatus: import('vue').Ref }}
 */
export function useBlockTree(graphStore) {
  const blockTree = ref({ stacks: [] });
  const kirText = ref("");
  // 'idle' | 'loading' | 'ready' | 'error' | 'fallback'
  const wasmStatus = ref("idle");

  // Debounce timer handle
  let rebuildTimer = null;

  async function rebuild() {
    const nodeList = graphStore.nodeList;
    const connectionList = graphStore.connectionList;

    if (!nodeList.length) {
      blockTree.value = { stacks: [] };
      kirText.value = "";
      return;
    }

    // Step 1: compile graph → KIR text (synchronous)
    // compileGraph returns { ir: string, errors: string[] }
    let kir = "";
    try {
      const result = compileGraph(nodeList, connectionList);
      kir = result.ir ?? "";
      if (result.errors?.length) {
        console.warn("[blockTree] compile warnings:", result.errors);
      }
    } catch (err) {
      console.warn("[blockTree] compileGraph failed:", err);
      kir = `# compile error: ${err.message}`;
    }
    kirText.value = kir;

    // Step 2: parse KIR → AST (asynchronous, requires Pyodide)
    if (!isWasmReady()) {
      wasmStatus.value = "loading";
      // Show fallback KIR text stack while waiting
      blockTree.value = makeFallbackTree(kir);
      // Start WASM loading (no-op if already in progress) then re-run
      // rebuild automatically once WASM is ready.
      initWasm().then((ok) => {
        if (ok) rebuild();
      });
      return;
    }

    wasmStatus.value = "loading";
    try {
      const ast = await parseKirToAst(kir);
      if (!ast) {
        wasmStatus.value = "fallback";
        blockTree.value = makeFallbackTree(kir);
        return;
      }
      wasmStatus.value = "ready";
      blockTree.value = astToBlockTree(ast);
    } catch (err) {
      console.warn("[blockTree] parseKirToAst failed:", err);
      wasmStatus.value = "error";
      blockTree.value = makeFallbackTree(kir);
    }
  }

  /**
   * Build a minimal block tree that just shows the raw KIR text when Pyodide
   * is not available. Each non-empty line becomes its own statement block.
   *
   * @param {string} kir
   * @returns {{ stacks: object[] }}
   */
  function makeFallbackTree(kir) {
    const lines = kir
      .split("\n")
      .filter((l) => l.trim() && !l.trim().startsWith("#"));
    if (!lines.length) return { stacks: [] };
    const blocks = lines.map((line, i) => ({
      type: "kir-line",
      key: `kir-${i}`,
      text: line,
    }));
    return { stacks: [{ key: "kir-fallback", blocks }] };
  }

  // Debounced re-build: avoid thrashing on rapid graph edits
  function scheduleRebuild() {
    if (rebuildTimer) clearTimeout(rebuildTimer);
    rebuildTimer = setTimeout(() => {
      rebuildTimer = null;
      rebuild();
    }, 80);
  }

  // Watch graph store for changes
  watch(
    () => [graphStore.nodeList, graphStore.connectionList],
    () => scheduleRebuild(),
    { deep: true, immediate: true },
  );

  return { blockTree, kirText, wasmStatus };
}
