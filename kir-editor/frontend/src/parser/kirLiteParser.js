/**
 * kirLiteParser.js
 * Lightweight regex-based KIR text extractor for visualization.
 *
 * Does NOT fully parse KIR — extracts enough topology (nodes + edges)
 * to render a node graph.  Use the Python interpreter for execution.
 *
 * Supported KIR constructs:
 *   @meta node_id="..." pos=(x, y) size=[w, h] ...
 *   (inputs)func_name(outputs)          — FuncCall / branch / switch / jump / parallel
 *   var = expr                          — Assignment → Value node
 *   label:                              — Namespace boundary
 *   @dataflow:                          — Dataflow block (no control edges inside)
 *   @mode ...                           — Ignored
 *   @def (params)name(outputs): ...     — Subgraph definition (treated as namespace)
 *   # comments                          — Stripped
 *
 * Variable naming convention: {node_id}_{port} → enables data-edge recovery.
 *
 * Auto-layout grid: col = index % 4, row = floor(index / 4), spacing 250×180.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const GRID_COLS = 4;
const GRID_COL_SPACING = 250;
const GRID_ROW_SPACING = 180;
const GRID_X0 = 100;
const GRID_Y0 = 100;

const CONTROL_BUILTINS = new Set(['branch', 'switch', 'jump', 'parallel']);

// ---------------------------------------------------------------------------
// Tokeniser helpers
// ---------------------------------------------------------------------------

/**
 * Strip comments and blank lines, preserving line numbers for indentation
 * tracking.  Triple-quoted strings are protected from comment stripping.
 *
 * Returns an array of { lineNo, indent, text } objects where:
 *   lineNo — 1-based original line number
 *   indent — number of leading spaces/tabs (tabs counted as 4 spaces)
 *   text   — stripped line content (no trailing whitespace, no comment)
 */
function tokeniseLines(src) {
  // Replace triple-quoted strings with a single-line placeholder so that
  // newlines inside them don't confuse the line-by-line processing.
  // We only need the placeholder to prevent false comment matches.
  const protected_ = [];
  const safeSrc = src.replace(/"""[\s\S]*?"""|'''[\s\S]*?'''/g, (m) => {
    const idx = protected_.length;
    protected_.push(m);
    // Replace with a single-quoted sentinel that contains no special chars
    return `"__TRIPLEQ_${idx}__"`;
  });

  const rawLines = safeSrc.split(/\r?\n/);
  const result = [];

  for (let i = 0; i < rawLines.length; i++) {
    let line = rawLines[i];

    // Strip inline comments (not inside strings).
    // Simple approach: strip everything after # that's not inside quotes.
    line = stripComment(line);

    // Measure indentation before stripping leading whitespace.
    const indentMatch = line.match(/^([ \t]*)/);
    let indent = 0;
    for (const ch of indentMatch[1]) {
      indent += ch === '\t' ? 4 : 1;
    }

    const text = line.trimEnd();
    if (text.trim() === '') continue; // skip blank / comment-only lines

    result.push({ lineNo: i + 1, indent, text: text.trim() });
  }

  return result;
}

/**
 * Strip a trailing # comment from a line, respecting quoted strings.
 * Triple-quoted strings have already been collapsed to single-line
 * sentinels by the caller.
 */
function stripComment(line) {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '\\' && (inSingle || inDouble)) {
      i++; // skip escaped char
      continue;
    }
    if (ch === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }
    if (ch === '"' && !inSingle) {
      inDouble = !inDouble;
      continue;
    }
    if (ch === '#' && !inSingle && !inDouble) {
      return line.slice(0, i);
    }
  }
  return line;
}

// ---------------------------------------------------------------------------
// @meta parser
// ---------------------------------------------------------------------------

/**
 * Parse a single @meta line into a key→value map.
 * Handles: key="string", key=42, key=3.14, key=(x, y), key=[w, h],
 *          key=True, key=False, key=None, key=identifier
 *
 * @param {string} text - The raw @meta line (may start with "@meta").
 * @returns {object} Map of key → parsed value.
 */
function parseMeta(text) {
  // Strip leading @meta
  const body = text.replace(/^\s*@meta\s*/, '');
  const result = {};

  // Regex: key=value where value is:
  //   "string" | 'string' | (x, y) | [a, b] | number | identifier
  const pairRe =
    /(\w+)\s*=\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\([\d\s.,+-]+\)|\[[\d\s.,+-]+\]|[^\s,]+)/g;
  let m;
  while ((m = pairRe.exec(body)) !== null) {
    const key = m[1];
    const raw = m[2];
    result[key] = parseMetaValue(raw);
  }
  return result;
}

function parseMetaValue(raw) {
  if (raw === undefined || raw === null) return raw;
  const s = String(raw).trim();

  // Tuple: (x, y)
  if (/^\(/.test(s)) {
    const nums = s
      .replace(/[()]/g, '')
      .split(',')
      .map((v) => parseFloat(v.trim()));
    return nums;
  }
  // List: [w, h]
  if (/^\[/.test(s)) {
    const nums = s
      .replace(/[\[\]]/g, '')
      .split(',')
      .map((v) => parseFloat(v.trim()));
    return nums;
  }
  // Quoted string
  if (/^["']/.test(s)) {
    try {
      // Use JSON.parse for double-quoted; fall back to slice for single-quoted
      if (s.startsWith('"')) return JSON.parse(s);
      return s.slice(1, -1);
    } catch {
      return s.slice(1, -1);
    }
  }
  // Bool / None
  if (s === 'True') return true;
  if (s === 'False') return false;
  if (s === 'None') return null;
  // Number
  const n = Number(s);
  if (!isNaN(n) && s !== '') return n;
  return s;
}

// ---------------------------------------------------------------------------
// Expression / argument parsers
// ---------------------------------------------------------------------------

/**
 * Split a comma-separated argument list respecting nested parens, brackets,
 * braces, and quoted strings.  Returns an array of trimmed token strings.
 */
function splitArgs(src) {
  const args = [];
  let depth = 0;
  let inSingle = false;
  let inDouble = false;
  let start = 0;

  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch === '\\' && (inSingle || inDouble)) {
      i++;
      continue;
    }
    if (ch === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }
    if (ch === '"' && !inSingle) {
      inDouble = !inDouble;
      continue;
    }
    if (inSingle || inDouble) continue;
    if (ch === '(' || ch === '[' || ch === '{') {
      depth++;
      continue;
    }
    if (ch === ')' || ch === ']' || ch === '}') {
      depth--;
      continue;
    }
    if (ch === ',' && depth === 0) {
      args.push(src.slice(start, i).trim());
      start = i + 1;
    }
  }
  const last = src.slice(start).trim();
  if (last !== '') args.push(last);
  return args;
}

/**
 * Parse the inputs section of a call: "(x, y, mode='fast')" → array of items.
 * Each item is { kind: 'pos'|'kw', name?, value }.
 */
function parseInputs(src) {
  const items = [];
  for (const tok of splitArgs(src)) {
    if (tok === '') continue;
    const kwMatch = tok.match(/^(\w+)\s*=\s*([\s\S]+)$/);
    if (kwMatch) {
      items.push({ kind: 'kw', name: kwMatch[1], value: kwMatch[2].trim() });
    } else {
      items.push({ kind: 'pos', value: tok });
    }
  }
  return items;
}

/**
 * Parse the outputs section of a call.
 * Covers: plain names, _, label refs `name`, switch cases expr=>`name`.
 * Returns array of { kind: 'name'|'wildcard'|'label'|'case'|'default', ... }.
 */
function parseOutputs(src) {
  const items = [];
  for (const tok of splitArgs(src)) {
    const t = tok.trim();
    if (t === '') continue;
    if (t === '_') {
      items.push({ kind: 'wildcard' });
    } else if (/^`[a-zA-Z_]\w*`$/.test(t)) {
      items.push({ kind: 'label', label: t.slice(1, -1) });
    } else if (/^_\s*=>\s*`[a-zA-Z_]\w*`$/.test(t)) {
      const label = t.match(/`([a-zA-Z_]\w*)`/)[1];
      items.push({ kind: 'default', label });
    } else {
      const caseMatch = t.match(/^(.+?)\s*=>\s*`([a-zA-Z_]\w*)`$/);
      if (caseMatch) {
        items.push({ kind: 'case', value: caseMatch[1].trim(), label: caseMatch[2] });
      } else {
        items.push({ kind: 'name', name: t });
      }
    }
  }
  return items;
}

/**
 * Determine whether a token looks like a literal (vs an identifier / variable).
 * Literals: numbers, quoted strings, True/False/None, lists, dicts.
 */
function isLiteral(tok) {
  const t = tok.trim();
  if (t === 'True' || t === 'False' || t === 'None') return true;
  if (/^-?[\d.]/.test(t) && !isNaN(Number(t))) return true;
  if (/^["'`\[\{]/.test(t)) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Source-line extraction — handles multi-line calls
// ---------------------------------------------------------------------------

/**
 * Join continuation lines for calls that span multiple lines due to open
 * parentheses.  Returns an array of logical statements (each already joined).
 *
 * Each element: { indent, text } where text is the joined logical line.
 */
function joinContinuations(lines) {
  const result = [];
  let depth = 0;
  let buf = null;
  let bufIndent = 0;

  for (const { indent, text } of lines) {
    if (buf === null) {
      // Start a new logical line
      buf = text;
      bufIndent = indent;
      depth = countDepth(text);
      if (depth === 0) {
        result.push({ indent: bufIndent, text: buf });
        buf = null;
      }
    } else {
      // Continue existing logical line
      buf += ' ' + text;
      depth += countDepth(text);
      if (depth <= 0) {
        result.push({ indent: bufIndent, text: buf });
        buf = null;
        depth = 0;
      }
    }
  }
  if (buf !== null) {
    result.push({ indent: bufIndent, text: buf });
  }
  return result;
}

function countDepth(text) {
  let d = 0;
  let inS = false,
    inD = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '\\' && (inS || inD)) {
      i++;
      continue;
    }
    if (ch === "'" && !inD) {
      inS = !inS;
      continue;
    }
    if (ch === '"' && !inS) {
      inD = !inD;
      continue;
    }
    if (inS || inD) continue;
    if (ch === '(' || ch === '[' || ch === '{') d++;
    else if (ch === ')' || ch === ']' || ch === '}') d--;
  }
  return d;
}

// ---------------------------------------------------------------------------
// Main parser state
// ---------------------------------------------------------------------------

/**
 * Parse KIR text and return a viewer graph.
 *
 * @param {string} kirText - KIR source text (L2 or L3, with or without @meta).
 * @returns {{ nodes: object[], edges: object[] }}
 */
export function parseKirLite(kirText) {
  // ---- Phase 0: tokenise & join continuations ----
  const rawLines = tokeniseLines(kirText);
  const logicalLines = joinContinuations(rawLines);

  // ---- Shared state ----
  const nodes = []; // viewer nodes (appended as discovered)
  const edges = []; // viewer edges (appended as discovered)

  // Map: variable_name → { nodeId, port }   (data output variables)
  const varMap = {};

  // Map: nodeId → viewer node (for fast lookup when emitting edges)
  const nodeById = {};

  // Auto-layout counter (used when @meta pos is absent)
  let autoIndex = 0;

  // ---- Helpers ----

  function autoPos() {
    const col = autoIndex % GRID_COLS;
    const row = Math.floor(autoIndex / GRID_COLS);
    autoIndex++;
    return {
      x: GRID_X0 + col * GRID_COL_SPACING,
      y: GRID_Y0 + row * GRID_ROW_SPACING,
    };
  }

  function resolvePos(meta) {
    if (meta && meta.pos && Array.isArray(meta.pos) && meta.pos.length >= 2) {
      return { x: Number(meta.pos[0]), y: Number(meta.pos[1]) };
    }
    return autoPos();
  }

  function resolveSize(meta) {
    if (meta && meta.size && Array.isArray(meta.size) && meta.size.length >= 2) {
      return { width: Number(meta.size[0]), height: Number(meta.size[1]) };
    }
    return { width: 180, height: 120 };
  }

  /**
   * Attempt to resolve an input token to a (nodeId, port) pair.
   * Uses the varMap built so far.
   * Returns null if the token is a literal or unknown variable.
   */
  function resolveVar(token) {
    const t = token.trim();
    if (isLiteral(t)) return null;
    if (varMap[t]) return varMap[t];
    return null;
  }

  // Store unresolved data inputs for Phase 3 (forward references in @dataflow:)
  const deferredDataInputs = [];

  function emitDataEdges(nodeId, inputItems, dataInputPortNames) {
    inputItems.forEach((inp, idx) => {
      let toPort;
      if (inp.kind === 'kw') {
        toPort = inp.name;
      } else {
        toPort = dataInputPortNames[idx] ?? `in_${idx}`;
      }

      const varRef = resolveVar(inp.value);
      if (varRef) {
        edges.push({
          type: 'data',
          fromNode: varRef.nodeId,
          fromPort: varRef.port,
          toNode: nodeId,
          toPort,
        });
      } else {
        // Forward reference — defer to Phase 3
        deferredDataInputs.push({ varName: inp.value, toNode: nodeId, toPort });
      }
    });
  }

  // Deferred label→namespace ctrl edges
  // Each: { fromNodeId, fromPort, label }
  const labelSources = [];

  // Deferred jump edges (jump is not a node, just a wire)
  // Each: { fromNodeId, fromPort, label }
  const jumpEdges = [];

  // Map: namespace_label → first node id inside that namespace
  const namespaceFirstNode = {}; // label → nodeId
  let currentNamespaceLabel = null; // set when we push a namespace scope

  // ---------------------------------------------------------------------------
  // Processing: Phase 1 builds nodes/varMap/labelSources in a single pass.
  // ---------------------------------------------------------------------------
  parsePhase1(logicalLines);

  // Phase 2: deferred label→namespace ctrl edges
  for (const { fromNodeId, fromPort, label } of labelSources) {
    const toNodeId = namespaceFirstNode[label];
    if (!toNodeId) continue;
    const fromNode = nodeById[fromNodeId];
    const toNode = nodeById[toNodeId];
    if (!fromNode || !toNode) continue;
    // Verify the fromPort is a ctrl output on the from-node
    if (!fromNode.ctrlOutputs.includes(fromPort)) continue;
    if (toNode.ctrlInputs.length === 0) continue;
    edges.push({
      type: 'control',
      fromNode: fromNodeId,
      fromPort,
      toNode: toNodeId,
      toPort: toNode.ctrlInputs[0],
    });
  }

  // Phase 3: resolve deferred data edges (forward references in @dataflow:)
  for (const { varName, toNode, toPort } of deferredDataInputs) {
    const varRef = resolveVar(varName);
    if (varRef) {
      edges.push({
        type: 'data',
        fromNode: varRef.nodeId,
        fromPort: varRef.port,
        toNode,
        toPort,
      });
    }
  }

  // Phase 4: wire jump edges (jump = ctrl wire, not a node)
  // Track how many ctrl edges arrive at each namespace target
  const nsIncomingCount = {}; // label → count
  for (const { label } of jumpEdges) {
    nsIncomingCount[label] = (nsIncomingCount[label] || 0) + 1;
  }
  for (const { label } of labelSources) {
    nsIncomingCount[label] = (nsIncomingCount[label] || 0) + 1;
  }

  // For namespaces with 2+ incoming ctrl edges, synthesize a merge node
  for (const [label, count] of Object.entries(nsIncomingCount)) {
    if (count >= 2) {
      const targetNodeId = namespaceFirstNode[label];
      if (!targetNodeId) continue;
      const targetNode = nodeById[targetNodeId];
      if (!targetNode) continue;

      const mergeId = `merge_${label}`;
      const mergeInputs = [];
      for (let mi = 0; mi < count; mi++) mergeInputs.push(`in_${mi}`);

      const mergeNode = {
        id: mergeId,
        type: 'merge',
        name: 'Merge',
        x: targetNode.x - 100,
        y: targetNode.y - 60,
        width: 140,
        height: 76,
        dataInputs: [],
        dataOutputs: [],
        ctrlInputs: mergeInputs,
        ctrlOutputs: ['out'],
      };
      nodes.push(mergeNode);
      nodeById[mergeId] = mergeNode;

      // Wire merge out → target node
      edges.push({
        type: 'control',
        fromNode: mergeId,
        fromPort: 'out',
        toNode: targetNodeId,
        toPort: targetNode.ctrlInputs[0] || 'in',
      });

      // Rewire existing labelSource edges to go to merge inputs
      let inputIdx = 0;
      // Rewire branch/switch/parallel edges that target this namespace
      for (let ei = edges.length - 1; ei >= 0; ei--) {
        const e = edges[ei];
        if (e.type === 'control' && e.toNode === targetNodeId) {
          // Redirect to merge
          e.toNode = mergeId;
          e.toPort = mergeInputs[inputIdx++] || `in_${inputIdx}`;
        }
      }

      // Wire jump edges to merge inputs
      for (const je of jumpEdges) {
        if (je.label === label && je.fromNodeId) {
          edges.push({
            type: 'control',
            fromNode: je.fromNodeId,
            fromPort: je.fromPort,
            toNode: mergeId,
            toPort: mergeInputs[inputIdx++] || `in_${inputIdx}`,
          });
        }
      }
    }
  }

  // Wire single-target jump edges (no merge needed)
  for (const { fromNodeId, fromPort, label } of jumpEdges) {
    if ((nsIncomingCount[label] || 0) < 2 && fromNodeId) {
      const toNodeId = namespaceFirstNode[label];
      if (!toNodeId) continue;
      const toNode = nodeById[toNodeId];
      if (!toNode) continue;
      edges.push({
        type: 'control',
        fromNode: fromNodeId,
        fromPort: fromPort,
        toNode: toNodeId,
        toPort: toNode.ctrlInputs[0] || 'in',
      });
    }
  }

  return { nodes, edges };

  // ---------------------------------------------------------------------------
  // Phase 1 implementation (uses closures above)
  // ---------------------------------------------------------------------------

  function parsePhase1(logicalLines) {
    const indentScopeStack = [{ indent: 0, label: null, inDataflow: false }];
    let pendingMetaLocal = {};

    // Control sequencing: per-scope "last node id"
    const prevNodeStack = [null]; // one per scope level

    function currentScope() {
      return indentScopeStack[indentScopeStack.length - 1];
    }
    function getPrev() {
      return prevNodeStack[prevNodeStack.length - 1];
    }
    function setPrev(id) {
      prevNodeStack[prevNodeStack.length - 1] = id;
    }

    function pushScope(label, inDataflow) {
      indentScopeStack.push({ label, inDataflow });
      prevNodeStack.push(null);
      currentNamespaceLabel = label;
    }
    function popScope() {
      indentScopeStack.pop();
      prevNodeStack.pop();
      currentNamespaceLabel = indentScopeStack[indentScopeStack.length - 1]?.label ?? null;
    }

    let nodeSeq = 0; // sequential counter for auto-generated ids

    function nextSeq() {
      return nodeSeq++;
    }

    function addNodeTracked(node) {
      nodes.push(node);
      nodeById[node.id] = node;
      const lbl = currentNamespaceLabel;
      if (lbl && !(lbl in namespaceFirstNode)) {
        namespaceFirstNode[lbl] = node.id;
      }
    }

    function doEmitCtrlEdge(toNodeId) {
      const scope = currentScope();
      if (scope.inDataflow) return;
      const prevId = getPrev();
      if (!prevId) return;
      const fromNode = nodeById[prevId];
      const toNode = nodeById[toNodeId];
      if (!fromNode || !toNode) return;
      const fromPort = fromNode.ctrlOutputs[0];
      const toPort = toNode.ctrlInputs[0];
      if (!fromPort || !toPort) return;
      edges.push({ type: 'control', fromNode: prevId, fromPort, toNode: toNodeId, toPort });
    }

    function doAdvanceCtrl(nodeId) {
      if (!currentScope().inDataflow) setPrev(nodeId);
    }

    const indentLevels = [0];

    for (let i = 0; i < logicalLines.length; i++) {
      const { indent, text } = logicalLines[i];

      // Sync dedents
      while (indentLevels.length > 1 && indent < indentLevels[indentLevels.length - 1]) {
        indentLevels.pop();
        popScope();
      }

      // ---- @mode ----
      if (/^@mode\b/.test(text)) continue;

      // ---- @meta ----
      if (/^@meta\b/.test(text)) {
        const meta = parseMeta(text);
        Object.assign(pendingMetaLocal, meta);
        continue;
      }

      // ---- @dataflow: ----
      if (/^@dataflow\s*:/.test(text)) {
        pushScope(null, true);
        indentLevels.push(indent + 1);
        continue;
      }

      // ---- @def ----
      if (/^@def\b/.test(text)) {
        // Extract name from @def (params)name(outputs):
        const defMatch = text.match(/^@def\s*\([^)]*\)\s*([a-zA-Z_]\w*)/);
        const defLabel = defMatch ? defMatch[1] : null;
        pushScope(defLabel, false);
        indentLevels.push(indent + 1);
        pendingMetaLocal = {};
        continue;
      }

      // ---- Namespace label ----
      if (/^[a-zA-Z_]\w*\s*:$/.test(text)) {
        const label = text.slice(0, -1).trim();
        pushScope(label, currentScope().inDataflow);
        indentLevels.push(indent + 1);
        pendingMetaLocal = {};
        continue;
      }

      // ---- Assignment ----
      {
        const am = text.match(/^([a-zA-Z_]\w*)\s*=\s*([\s\S]+)$/);
        if (am) {
          const varName = am[1];
          const meta = pendingMetaLocal;
          pendingMetaLocal = {};

          const nodeId = meta.node_id ?? `val_${varName}_${nextSeq()}`;
          let { x, y } = resolvePos(meta);
          if (!meta.pos) {
            const ap = autoPos();
            x = ap.x;
            y = ap.y;
          }
          const { width, height } = resolveSize(meta);

          const node = {
            id: nodeId,
            type: 'value',
            name: varName,
            x,
            y,
            width,
            height,
            dataInputs: [],
            dataOutputs: [{ name: 'value', type: 'any' }],
            ctrlInputs: [],
            ctrlOutputs: [],
          };

          addNodeTracked(node);

          // Register variable
          varMap[varName] = { nodeId, port: 'value' };
          varMap[`${nodeId}_value`] = { nodeId, port: 'value' };

          doEmitCtrlEdge(nodeId);
          doAdvanceCtrl(nodeId);
          continue;
        }
      }

      // ---- FuncCall ----
      {
        // Match: (inputs)func_name(outputs)
        // The inputs/outputs may be complex — extract balanced parens.
        const callMatch = extractCall(text);
        if (callMatch) {
          const { rawInputs, funcName, rawOutputs } = callMatch;
          const meta = pendingMetaLocal;
          pendingMetaLocal = {};

          const inputItems = parseInputs(rawInputs);
          const outputItems = parseOutputs(rawOutputs);
          const fnLower = funcName.toLowerCase();

          const nodeId = meta.node_id ?? `${funcName.replace(/\./g, '_')}_${nextSeq()}`;
          let { x, y } = resolvePos(meta);
          if (!meta.pos) {
            const ap = autoPos();
            x = ap.x;
            y = ap.y;
          }
          const { width, height } = resolveSize(meta);

          let dataInputs = [];
          let dataOutputs = [];
          let ctrlInputs = [];
          let ctrlOutputs = [];

          if (fnLower === 'branch') {
            dataInputs = [{ name: 'condition', type: 'bool' }];
            ctrlInputs = ['in'];
            ctrlOutputs = outputItems.filter((o) => o.kind === 'label').map((o) => o.label);
            if (ctrlOutputs.length === 0) ctrlOutputs = ['true', 'false'];
          } else if (fnLower === 'switch') {
            dataInputs = [{ name: 'value', type: 'any' }];
            ctrlInputs = ['in'];
            ctrlOutputs = outputItems
              .filter((o) => o.kind === 'case' || o.kind === 'default')
              .map((o) => o.label);
          } else if (fnLower === 'jump') {
            // jump is NOT a visible node — it's a ctrl wire.
            // Store a deferred edge from the current scope's last node to the target.
            const prevId = getPrev();
            for (const out of outputItems) {
              if (out.kind === 'label') {
                if (prevId) {
                  const fromNode = nodeById[prevId];
                  const fromPort = fromNode ? fromNode.ctrlOutputs[0] || 'out' : 'out';
                  jumpEdges.push({ fromNodeId: prevId, fromPort, label: out.label });
                } else {
                  jumpEdges.push({ fromNodeId: null, fromPort: null, label: out.label });
                }
              }
            }
            // Don't create a node, don't advance ctrl
            pendingMetaLocal = {};
            continue;
          } else if (fnLower === 'parallel') {
            ctrlInputs = ['in'];
            ctrlOutputs = outputItems.filter((o) => o.kind === 'label').map((o) => o.label);
          } else {
            ctrlInputs = ['in'];
            ctrlOutputs = ['out'];

            inputItems.forEach((inp, idx) => {
              const portName = inp.kind === 'kw' ? inp.name : `in_${idx}`;
              dataInputs.push({ name: portName, type: 'any' });
            });

            outputItems.forEach((out, idx) => {
              if (out.kind === 'name') {
                dataOutputs.push({ name: out.name, type: 'any' });
              } else if (out.kind === 'wildcard') {
                dataOutputs.push({ name: `_out_${idx}`, type: 'any' });
              }
            });
          }

          const node = {
            id: nodeId,
            type:
              fnLower === 'branch'
                ? 'branch'
                : fnLower === 'switch'
                  ? 'switch'
                  : fnLower === 'jump'
                    ? 'jump'
                    : fnLower === 'parallel'
                      ? 'parallel'
                      : funcName,
            name: funcName,
            x,
            y,
            width,
            height,
            dataInputs,
            dataOutputs,
            ctrlInputs,
            ctrlOutputs,
          };

          addNodeTracked(node);

          // Register raw output names as data variables
          for (const out of outputItems) {
            if (out.kind === 'name') {
              varMap[out.name] = { nodeId, port: out.name };
              // Also {nodeId}_{portName} form
              varMap[`${nodeId}_${out.name}`] = { nodeId, port: out.name };
            }
          }
          for (const out of dataOutputs) {
            varMap[`${nodeId}_${out.name}`] = { nodeId, port: out.name };
          }

          // Emit data edges
          emitDataEdges(
            nodeId,
            inputItems,
            dataInputs.map((p) => p.name)
          );

          // Emit sequential ctrl edge
          doEmitCtrlEdge(nodeId);
          doAdvanceCtrl(nodeId);

          // Register deferred label ctrl edges
          for (const out of outputItems) {
            if (out.kind === 'label' || out.kind === 'case' || out.kind === 'default') {
              labelSources.push({ fromNodeId: nodeId, fromPort: out.label, label: out.label });
            }
          }

          continue;
        }
      }

      // Unknown line — ignore
      pendingMetaLocal = {};
    }
  }
}

/**
 * Extract the three parts of a KIR call from a single logical line.
 * Returns { rawInputs, funcName, rawOutputs } or null.
 *
 * Handles: (inputs)name(outputs)
 *
 * The tricky part: rawInputs may contain nested parens.
 * We find the matching closing paren for the first open paren.
 */
function extractCall(text) {
  const t = text.trim();
  if (!t.startsWith('(')) return null;

  // Find matching ) for the first (
  let depth = 0;
  let inS = false,
    inD = false;
  let closeIdx = -1;
  for (let i = 0; i < t.length; i++) {
    const ch = t[i];
    if (ch === '\\' && (inS || inD)) {
      i++;
      continue;
    }
    if (ch === "'" && !inD) {
      inS = !inS;
      continue;
    }
    if (ch === '"' && !inS) {
      inD = !inD;
      continue;
    }
    if (inS || inD) continue;
    if (ch === '(') depth++;
    else if (ch === ')') {
      depth--;
      if (depth === 0) {
        closeIdx = i;
        break;
      }
    }
  }
  if (closeIdx < 0) return null;

  const rawInputs = t.slice(1, closeIdx);
  const rest = t.slice(closeIdx + 1).trim();

  // rest: funcName(outputs)
  const nameMatch = rest.match(/^([a-zA-Z_][\w.]*)\s*\(([\s\S]*)\)$/);
  if (!nameMatch) return null;

  return {
    rawInputs,
    funcName: nameMatch[1],
    rawOutputs: nameMatch[2],
  };
}
