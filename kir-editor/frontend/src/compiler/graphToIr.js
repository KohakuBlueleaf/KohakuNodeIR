/**
 * graphToIr.js — Graph-to-KIR compiler
 *
 * Converts the graph store state (nodes + connections) into valid .kir IR text.
 * Supports both controlflow and dataflow compilation modes.
 *
 * Also exports compileViaKirgraph / compileKirgraphToKir for the L1 → L2
 * pipeline that goes through the .kirgraph intermediate format.
 */

import { graphToKirgraph } from './kirgraph.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Sanitize a node ID for use in variable names.
 * Strips the 'node-' prefix and replaces non-alphanumeric chars with '_'.
 */
function shortId(nodeId) {
  return nodeId.replace(/^node-/, '').replace(/[^a-zA-Z0-9_]/g, '_')
}

/**
 * Build a valid KIR variable name for a data output port.
 * For value nodes, use the node name as the variable name.
 */
function varName(nodeId, portName) {
  const clean = portName.replace(/[^a-zA-Z0-9_]/g, '_')
  return `v_${shortId(nodeId)}_${clean}`
}

/**
 * Get the output variable name for a node's port, considering value nodes.
 * Value nodes use their name as the variable (e.g., "counter" not "v_value_3_value").
 *
 * All other nodes always include a node identifier prefix to avoid collisions
 * when multiple nodes have the same port name.
 */
function outputVarName(node, portName) {
  if (node.type === 'value' && node.name && node.name !== 'Node' && node.name !== 'value') {
    return sanitizeIdent(node.name)
  }
  return varName(node.id, portName)
}

/**
 * Sanitize an identifier to be valid in KIR (letters, digits, underscores, dots).
 */
function sanitizeIdent(name) {
  return name.replace(/[^a-zA-Z0-9_.]/g, '_').replace(/^(\d)/, '_$1')
}

/**
 * Format a literal value for KIR output.
 * Follows Python-style literals: strings get quotes, bools become True/False,
 * null/undefined become None, numbers stay as-is.
 */
function formatLiteral(value, dataType) {
  if (value === null || value === undefined) return 'None'
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  if (typeof value === 'string') {
    // Use double quotes, escaping internal double quotes
    const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
    return `"${escaped}"`
  }
  if (typeof value === 'number') return String(value)
  // Arrays and objects: JSON-like but with Python syntax
  if (Array.isArray(value)) {
    return '[' + value.map(v => formatLiteral(v)).join(', ') + ']'
  }
  if (typeof value === 'object') {
    const pairs = Object.entries(value).map(
      ([k, v]) => `${formatLiteral(k)}: ${formatLiteral(v)}`
    )
    return '{' + pairs.join(', ') + '}'
  }
  return String(value)
}

/**
 * Sanitize a namespace label — must be a valid KIR identifier.
 */
function nsLabel(base) {
  return sanitizeIdent(base).toLowerCase()
}

/**
 * Return a stable loop/merge label for a merge node.
 */
function mergeLabel(node) {
  return nsLabel(`loop_${shortId(node.id)}`)
}

/**
 * Determine whether a merge node is a loop merge (has a back-edge).
 * A merge is a loop merge if at least one of its ctrl inputs originates
 * from a node reachable by walking ctrl edges *forward* from the merge itself.
 *
 * We do a forward DFS from the merge node; if we encounter a node whose ctrl
 * output reaches back to the merge, the merge is a loop header.
 */
function isLoopMerge(mergeNode, idx) {
  const reachable = new Set()
  const stack = [mergeNode.id]
  while (stack.length > 0) {
    const id = stack.pop()
    if (reachable.has(id)) continue
    reachable.add(id)
    const outConns = idx.ctrlOutByNode.get(id) ?? []
    for (const conn of outConns) {
      if (!reachable.has(conn.toNodeId)) stack.push(conn.toNodeId)
    }
  }
  // Check if any ctrl-input of the merge comes from a reachable node
  const inConns = idx.ctrlInByNode.get(mergeNode.id) ?? []
  for (const conn of inConns) {
    if (reachable.has(conn.fromNodeId)) return true
  }
  return false
}

// ---------------------------------------------------------------------------
// Adjacency / index builders
// ---------------------------------------------------------------------------

/**
 * Build lookup structures from the flat node and connection lists.
 */
function buildIndices(nodeList, connectionList) {
  const nodeMap = new Map()          // nodeId -> node
  for (const n of nodeList) nodeMap.set(n.id, n)

  // Control connections: from (nodeId, portId) -> to (nodeId, portId)
  const ctrlOutEdges = new Map()     // "fromNodeId:fromPortId" -> { toNodeId, toPortId, conn }
  const ctrlInEdges = new Map()      // "toNodeId:toPortId" -> { fromNodeId, fromPortId, conn }
  const ctrlInByNode = new Map()     // nodeId -> [conn, ...]
  const ctrlOutByNode = new Map()    // nodeId -> [conn, ...]

  // Data connections
  const dataInEdges = new Map()      // "toNodeId:toPortId" -> { fromNodeId, fromPortId, conn }
  const dataOutEdges = new Map()     // "fromNodeId:fromPortId" -> [{ toNodeId, toPortId, conn }, ...]

  for (const conn of connectionList) {
    if (conn.portType === 'control') {
      const key = `${conn.fromNodeId}:${conn.fromPortId}`
      ctrlOutEdges.set(key, { toNodeId: conn.toNodeId, toPortId: conn.toPortId, conn })

      const inKey = `${conn.toNodeId}:${conn.toPortId}`
      ctrlInEdges.set(inKey, { fromNodeId: conn.fromNodeId, fromPortId: conn.fromPortId, conn })

      if (!ctrlInByNode.has(conn.toNodeId)) ctrlInByNode.set(conn.toNodeId, [])
      ctrlInByNode.get(conn.toNodeId).push(conn)

      if (!ctrlOutByNode.has(conn.fromNodeId)) ctrlOutByNode.set(conn.fromNodeId, [])
      ctrlOutByNode.get(conn.fromNodeId).push(conn)
    } else {
      // data
      const inKey = `${conn.toNodeId}:${conn.toPortId}`
      dataInEdges.set(inKey, { fromNodeId: conn.fromNodeId, fromPortId: conn.fromPortId, conn })

      const outKey = `${conn.fromNodeId}:${conn.fromPortId}`
      if (!dataOutEdges.has(outKey)) dataOutEdges.set(outKey, [])
      dataOutEdges.get(outKey).push({ toNodeId: conn.toNodeId, toPortId: conn.toPortId, conn })
    }
  }

  return {
    nodeMap,
    ctrlOutEdges, ctrlInEdges,
    ctrlInByNode, ctrlOutByNode,
    dataInEdges, dataOutEdges,
  }
}

// ---------------------------------------------------------------------------
// Data input resolution
// ---------------------------------------------------------------------------

/**
 * Resolve the KIR expression for a data input port.
 * If connected: return the variable name of the source output port.
 * If not connected: return the formatted default value or throw.
 */
function resolveInput(node, inputPort, idx) {
  const key = `${node.id}:${inputPort.id}`
  const edge = idx.dataInEdges.get(key)

  if (edge) {
    // Find the source port name
    const srcNode = idx.nodeMap.get(edge.fromNodeId)
    if (!srcNode) return 'None'
    const srcPort = srcNode.dataPorts.outputs.find(p => p.id === edge.fromPortId)
    if (!srcPort) return 'None'
    return outputVarName(srcNode, srcPort.name)
  }

  // Not connected — use default value (note: false and 0 are valid defaults)
  if (inputPort.defaultValue !== undefined && inputPort.defaultValue !== null) {
    return formatLiteral(inputPort.defaultValue, inputPort.dataType)
  }

  // No connection and no default
  return 'None'
}

// ---------------------------------------------------------------------------
// Meta emission
// ---------------------------------------------------------------------------

function emitMeta(node, indent) {
  const pad = '    '.repeat(indent)
  return `${pad}@meta node_id="${node.id}" pos=(${Math.round(node.x)}, ${Math.round(node.y)})`
}

// ---------------------------------------------------------------------------
// Node type -> KIR statement
// ---------------------------------------------------------------------------

/**
 * Emit the KIR statement(s) for a single node.
 * Returns an array of lines (without trailing newlines).
 *
 * @param {string|null} enclosingLoopLabel - label of the innermost enclosing loop,
 *   passed down into branch/switch/parallel arm emission.
 * @param {Set|null} emitted - optional set to track emitted node IDs.
 *   When provided, branch/switch/parallel arm nodes are added to the set so the
 *   outer compiler loop knows not to double-emit them.
 */
function emitNode(node, idx, indent, enclosingLoopLabel = null, emitted = null) {
  const pad = '    '.repeat(indent)
  const lines = []

  // Always emit metadata
  lines.push(emitMeta(node, indent))

  switch (node.type) {
    case 'value':
      lines.push(...emitValueNode(node, idx, pad))
      break
    case 'branch':
      lines.push(...emitBranchNode(node, idx, pad, indent, enclosingLoopLabel, emitted))
      break
    case 'switch':
      lines.push(...emitSwitchNode(node, idx, pad, indent, enclosingLoopLabel, emitted))
      break
    case 'merge':
      // Merge is handled structurally — it's a namespace label / convergence point.
      // When encountered in a walk, we just emit a comment.
      lines.push(`${pad}# merge point`)
      break
    case 'parallel':
      lines.push(...emitParallelNode(node, idx, pad, indent, enclosingLoopLabel, emitted))
      break
    default:
      // Generic function call: math, comparison, string, file, display, user-defined
      lines.push(...emitFunctionNode(node, idx, pad))
      break
  }

  return lines
}

/**
 * Value node: `varname = literal`
 */
function emitValueNode(node, idx, pad) {
  const outPort = node.dataPorts.outputs[0]
  if (!outPort) return [`${pad}# value node with no output port`]

  const vn = outputVarName(node, outPort.name)

  // Determine the value — from properties or a sensible default
  let val = 'None'
  if (node.properties?.value !== undefined) {
    val = formatLiteral(node.properties.value, node.properties?.valueType)
  } else if (node.properties?.valueType === 'int') {
    val = '0'
  } else if (node.properties?.valueType === 'float') {
    val = '0.0'
  } else if (node.properties?.valueType === 'str') {
    val = '""'
  } else if (node.properties?.valueType === 'bool') {
    val = 'False'
  }

  return [`${pad}${vn} = ${val}`]
}

/**
 * Generic function call: `(inputs)func_name(outputs)`
 */
function emitFunctionNode(node, idx, pad) {
  const funcName = sanitizeIdent(node.type)

  // Resolve inputs
  const inputArgs = node.dataPorts.inputs.map(port => resolveInput(node, port, idx))

  // Build output variable names
  const outputVars = node.dataPorts.outputs.map(port => outputVarName(node, port.name))

  // If no outputs, use empty parens
  const inputStr = inputArgs.join(', ')
  const outputStr = outputVars.join(', ')

  return [`${pad}(${inputStr})${funcName}(${outputStr})`]
}

/**
 * Branch node: `(condition)branch(\`true_ns\`, \`false_ns\`)`
 * Then emit the two branch namespaces by walking control outputs.
 *
 * @param {string|null} enclosingLoopLabel - label of the innermost enclosing loop,
 *   if any.  When a branch arm has no ctrl connection and we are inside a loop,
 *   the arm is a "continue" arm and should emit `()jump(\`loop\`)`.
 */
function emitBranchNode(node, idx, pad, indent, enclosingLoopLabel = null, emitted = null) {
  const lines = []

  // Resolve the condition input
  const condPort = node.dataPorts.inputs[0]
  const condExpr = condPort ? resolveInput(node, condPort, idx) : 'False'

  // Find the control output ports.  Use port names as namespace labels when they
  // are meaningful (e.g. "continue"/"done"), otherwise fall back to "true"/"false".
  const outPorts = node.controlPorts.outputs
  const port0 = outPorts[0]
  const port1 = outPorts[1]

  // Derive namespace names from the port names when they are user-visible labels
  // (not the generic "true"/"false" defaults), so round-tripped KIR looks clean.
  function branchNsName(port, fallback) {
    if (!port) return nsLabel(fallback)
    const n = port.name
    if (n && n !== 'true' && n !== 'false' && !/^(out|in_\d+|_out_\d+)$/.test(n)) {
      return nsLabel(n)
    }
    return nsLabel(fallback)
  }

  const trueNs  = branchNsName(port0, `br_${shortId(node.id)}_true`)
  const falseNs = branchNsName(port1, `br_${shortId(node.id)}_false`)

  lines.push(`${pad}(${condExpr})branch(\`${trueNs}\`, \`${falseNs}\`)`)

  // Keywords that suggest a branch arm exits a loop (done / break)
  const LOOP_EXIT_NAMES = new Set(['done', 'exit', 'break', 'end', 'stop', 'false', 'finish'])

  // Helper: emit one branch arm, tracking emitted nodes in the optional set
  function emitArm(port, nsName) {
    if (!port) return
    const { chain, loopJumpLabel } = walkControlChain(node.id, port.id, idx)
    lines.push(`${pad}${nsName}:`)
    if (chain.length > 0) {
      for (const chainNode of chain) {
        if (emitted) emitted.add(chainNode.id)
        lines.push(...emitNode(chainNode, idx, indent + 1, enclosingLoopLabel, emitted))
      }
    }
    // Determine if this arm should emit a jump back to an enclosing loop.
    // An explicit loopJumpLabel from the walk takes highest priority.
    // Falling back to enclosingLoopLabel only when:
    //   - the chain is empty (no nodes in this arm), AND
    //   - the port name does NOT suggest "exit" semantics.
    let jumpTarget = loopJumpLabel ?? null
    if (!jumpTarget && chain.length === 0 && enclosingLoopLabel) {
      const portNameLower = (port.name ?? '').toLowerCase()
      const looksLikeExit = LOOP_EXIT_NAMES.has(portNameLower) ||
        portNameLower.includes('exit') || portNameLower.includes('done') ||
        portNameLower.includes('end')  || portNameLower.includes('break')
      if (!looksLikeExit) {
        jumpTarget = enclosingLoopLabel
      }
    }
    if (jumpTarget) {
      lines.push(`${pad}    ()jump(\`${jumpTarget}\`)`)
    }
    // Empty arm with no jump — genuinely empty namespace (exit from loop)
  }

  emitArm(port0, trueNs)
  emitArm(port1, falseNs)

  return lines
}

/**
 * Switch node: `(value)switch(case0=>\`ns0\`, case1=>\`ns1\`, ...)`
 */
function emitSwitchNode(node, idx, pad, indent, enclosingLoopLabel = null, emitted = null) {
  const lines = []

  // Resolve the value input
  const valPort = node.dataPorts.inputs[0]
  const valExpr = valPort ? resolveInput(node, valPort, idx) : 'None'

  // Build case mappings from control output ports
  const cases = []
  for (const ctrlOut of node.controlPorts.outputs) {
    const caseName = ctrlOut.name
    const caseNs = nsLabel(`sw_${shortId(node.id)}_${sanitizeIdent(caseName)}`)

    // Extract case value from the port name (e.g. "case 0" -> 0, "case 1" -> 1)
    const caseMatch = caseName.match(/(\d+)/)
    const caseVal = caseMatch ? caseMatch[1] : `"${caseName}"`

    cases.push({ ctrlOut, caseVal, caseNs })
  }

  // Emit switch statement
  const caseArgs = cases.map(c => `${c.caseVal}=>\`${c.caseNs}\``).join(', ')
  lines.push(`${pad}(${valExpr})switch(${caseArgs})`)

  // Emit each case namespace
  for (const c of cases) {
    const { chain, loopJumpLabel } = walkControlChain(node.id, c.ctrlOut.id, idx)
    lines.push(`${pad}${c.caseNs}:`)
    if (chain.length > 0) {
      for (const chainNode of chain) {
        if (emitted) emitted.add(chainNode.id)
        lines.push(...emitNode(chainNode, idx, indent + 1, enclosingLoopLabel, emitted))
      }
    }
    const jumpTarget = loopJumpLabel ?? (chain.length === 0 ? enclosingLoopLabel : null)
    if (jumpTarget) {
      lines.push(`${pad}    ()jump(\`${jumpTarget}\`)`)
    } else if (chain.length === 0) {
      lines.push(`${pad}    # (empty case)`)
    }
  }

  return lines
}

/**
 * Parallel node: `()parallel(\`ns0\`, \`ns1\`, ...)`
 */
function emitParallelNode(node, idx, pad, indent, enclosingLoopLabel = null, emitted = null) {
  const lines = []

  const branches = []
  for (let i = 0; i < node.controlPorts.outputs.length; i++) {
    const ctrlOut = node.controlPorts.outputs[i]
    const branchNs = nsLabel(`par_${shortId(node.id)}_${i}`)
    branches.push({ ctrlOut, branchNs })
  }

  const nsArgs = branches.map(b => `\`${b.branchNs}\``).join(', ')
  lines.push(`${pad}()parallel(${nsArgs})`)

  for (const b of branches) {
    const { chain, loopJumpLabel } = walkControlChain(node.id, b.ctrlOut.id, idx)
    lines.push(`${pad}${b.branchNs}:`)
    if (chain.length > 0) {
      for (const chainNode of chain) {
        if (emitted) emitted.add(chainNode.id)
        lines.push(...emitNode(chainNode, idx, indent + 1, enclosingLoopLabel, emitted))
      }
    }
    const jumpTarget = loopJumpLabel ?? (chain.length === 0 ? enclosingLoopLabel : null)
    if (jumpTarget) {
      lines.push(`${pad}    ()jump(\`${jumpTarget}\`)`)
    } else if (chain.length === 0) {
      lines.push(`${pad}    # (empty parallel branch)`)
    }
  }

  return lines
}

// ---------------------------------------------------------------------------
// Control flow walking
// ---------------------------------------------------------------------------

/**
 * Walk the control chain starting from a specific control output port.
 * Returns { chain, loopJumpLabel } where:
 *   chain         — ordered array of nodes to emit
 *   loopJumpLabel — if the chain terminated at a loop-merge node, the merge's
 *                   label string (so the caller can emit a `()jump(...)` line);
 *                   null if termination was at a convergence merge or dead end.
 */
function walkControlChain(fromNodeId, fromPortId, idx) {
  const chain = []
  const visited = new Set()
  let currentNodeId = fromNodeId
  let currentPortId = fromPortId

  while (true) {
    const edgeKey = `${currentNodeId}:${currentPortId}`
    const edge = idx.ctrlOutEdges.get(edgeKey)
    if (!edge) break

    const nextNode = idx.nodeMap.get(edge.toNodeId)
    if (!nextNode) break

    // Avoid infinite loops from visiting the same node twice
    if (visited.has(nextNode.id)) break
    visited.add(nextNode.id)

    // If this node is a merge, determine if it is a loop merge or convergence.
    if (nextNode.type === 'merge') {
      if (isLoopMerge(nextNode, idx)) {
        // Loop back-edge: tell the caller to emit a jump to the loop label.
        return { chain, loopJumpLabel: mergeLabel(nextNode) }
      }
      // Convergence merge — stop; the parent scope continues from here.
      break
    }

    chain.push(nextNode)

    // For branch/switch/parallel: sub-chains are emitted inside emitNode.
    // After them, look for a merge node to continue from.
    if (nextNode.type === 'branch' || nextNode.type === 'switch' || nextNode.type === 'parallel') {
      const mergeNode = findMergeAfter(nextNode, idx)
      if (mergeNode) {
        if (isLoopMerge(mergeNode, idx)) {
          return { chain, loopJumpLabel: mergeLabel(mergeNode) }
        }
        const mergeOutPort = mergeNode.controlPorts.outputs[0]
        if (mergeOutPort) {
          currentNodeId = mergeNode.id
          currentPortId = mergeOutPort.id
          continue
        }
      }
      break
    }

    // For regular nodes, follow the first control output
    const outPort = nextNode.controlPorts.outputs[0]
    if (!outPort) break

    currentNodeId = nextNode.id
    currentPortId = outPort.id
  }

  return { chain, loopJumpLabel: null }
}

/**
 * Find the merge node that gathers the outputs of a branching node.
 * We walk all branches from the branching node and find the first node
 * that appears as a target from multiple branches — that's the merge.
 */
function findMergeAfter(branchingNode, idx) {
  // For each control output of the branching node, walk the chain and
  // collect all merge nodes reachable.
  const visited = new Set()

  function walkToMerge(nodeId, portId, depth) {
    if (depth > 100) return null // safety limit
    const edgeKey = `${nodeId}:${portId}`
    const edge = idx.ctrlOutEdges.get(edgeKey)
    if (!edge) return null

    const nextNode = idx.nodeMap.get(edge.toNodeId)
    if (!nextNode) return null

    if (nextNode.type === 'merge') return nextNode

    if (visited.has(nextNode.id)) return null
    visited.add(nextNode.id)

    // If it's another branching node, recurse deeper
    if (nextNode.type === 'branch' || nextNode.type === 'switch' || nextNode.type === 'parallel') {
      // Find its merge first
      const innerMerge = findMergeAfter(nextNode, idx)
      if (innerMerge) {
        const mergeOut = innerMerge.controlPorts.outputs[0]
        if (mergeOut) {
          return walkToMerge(innerMerge.id, mergeOut.id, depth + 1)
        }
      }
      return null
    }

    // Regular node — continue walking
    const outPort = nextNode.controlPorts.outputs[0]
    if (!outPort) return null
    return walkToMerge(nextNode.id, outPort.id, depth + 1)
  }

  // Check each branch output
  for (const ctrlOut of branchingNode.controlPorts.outputs) {
    const merge = walkToMerge(branchingNode.id, ctrlOut.id, 0)
    if (merge) return merge
  }

  return null
}

/**
 * Find the entry point node: a node with control ports but no incoming control connections.
 * For control flow mode, this is where execution starts.
 */
function findEntryNodes(nodeList, idx) {
  const entries = []

  for (const node of nodeList) {
    // Only consider nodes that participate in control flow
    const hasCtrlPorts = node.controlPorts.inputs.length > 0 || node.controlPorts.outputs.length > 0

    if (!hasCtrlPorts) continue

    // Entry node: has control output(s) but no incoming control connections
    const incomingCtrl = idx.ctrlInByNode.get(node.id)
    if (!incomingCtrl || incomingCtrl.length === 0) {
      entries.push(node)
    }
  }

  // Sort by y position (top-most first), then x
  entries.sort((a, b) => a.y - b.y || a.x - b.x)

  return entries
}

/**
 * Find nodes that are purely data-only (no control ports at all).
 * These are typically value nodes that feed into the control flow.
 */
function findPureDataNodes(nodeList) {
  return nodeList.filter(n =>
    n.controlPorts.inputs.length === 0 &&
    n.controlPorts.outputs.length === 0
  )
}

/**
 * Find nodes that have ctrl ports but NO ctrl connections at all.
 * These are typically function nodes that live inside @dataflow: blocks
 * in the original KIR source.  They should be emitted as @dataflow: blocks
 * rather than inline in the control flow.
 *
 * "No ctrl connections" means: no entry in ctrlInByNode AND no entry in ctrlOutByNode
 * (or all entries are empty).
 */
function findDisconnectedCtrlNodes(nodeList, idx) {
  return nodeList.filter(n => {
    if (n.controlPorts.inputs.length === 0 && n.controlPorts.outputs.length === 0) return false
    const hasCtrlIn  = (idx.ctrlInByNode.get(n.id)  ?? []).length > 0
    const hasCtrlOut = (idx.ctrlOutByNode.get(n.id) ?? []).length > 0
    return !hasCtrlIn && !hasCtrlOut
  })
}

/**
 * Collect the transitive data-source nodes for a node: all nodes whose data
 * outputs feed (directly or indirectly) into any data input of `node`.
 * Returns them in topological order (sources first).
 */
function collectDataDeps(node, idx, excludeSet) {
  const order = []
  const visited = new Set()

  function dfs(n) {
    if (visited.has(n.id)) return
    visited.add(n.id)
    for (const port of n.dataPorts.inputs) {
      const key  = `${n.id}:${port.id}`
      const edge = idx.dataInEdges.get(key)
      if (!edge) continue
      const src = idx.nodeMap.get(edge.fromNodeId)
      if (!src || excludeSet.has(src.id)) continue
      dfs(src)
    }
    if (!excludeSet.has(n.id)) order.push(n)
  }

  // We want deps OF node, not including node itself
  for (const port of node.dataPorts.inputs) {
    const key  = `${node.id}:${port.id}`
    const edge = idx.dataInEdges.get(key)
    if (!edge) continue
    const src = idx.nodeMap.get(edge.fromNodeId)
    if (!src || excludeSet.has(src.id)) continue
    dfs(src)
  }
  // Remove node itself if it snuck in
  return order.filter(n => n.id !== node.id)
}

/**
 * Walk the ctrl chain starting at `startNodeId` and collect all node IDs
 * reachable through control edges (following first ctrl output, stopping at
 * merges or dead ends).  Results are added to `out` (a Set).
 */
function collectCtrlChain(startNodeId, idx, out) {
  const stack = [startNodeId]
  while (stack.length > 0) {
    const nodeId = stack.pop()
    if (!nodeId || out.has(nodeId)) continue
    out.add(nodeId)
    const node = idx.nodeMap.get(nodeId)
    if (!node || node.type === 'merge') continue
    // For branch/switch/parallel follow all ctrl outputs
    for (const port of node.controlPorts.outputs) {
      const edgeKey = `${node.id}:${port.id}`
      const edge    = idx.ctrlOutEdges.get(edgeKey)
      if (edge && edge.toNodeId !== node.id) stack.push(edge.toNodeId)
    }
  }
}

/**
 * Returns true if the ctrl chain from `entryNode` terminates "open" — meaning
 * the chain ends at a branch/switch/parallel whose ctrl output ports have NO
 * outgoing ctrl connections.  This indicates that the back-edge(s) from the
 * loop body were lost during import.
 */
function ctrlChainTerminatesOpen(entryNode, idx) {
  const visited = new Set()

  function walk(node) {
    if (!node || visited.has(node.id)) return false
    visited.add(node.id)

    if (node.type === 'branch' || node.type === 'switch' || node.type === 'parallel') {
      // Check if ALL ctrl outputs of this node have no connections
      let allOpen = true
      for (const port of node.controlPorts.outputs) {
        const edgeKey = `${node.id}:${port.id}`
        const edge    = idx.ctrlOutEdges.get(edgeKey)
        if (edge && edge.toNodeId !== node.id) { allOpen = false; break }
      }
      return allOpen
    }

    const outPort = node.controlPorts.outputs[0]
    if (!outPort) return false
    const edgeKey = `${node.id}:${outPort.id}`
    const edge    = idx.ctrlOutEdges.get(edgeKey)
    if (!edge || edge.toNodeId === node.id) return false
    const nextNode = idx.nodeMap.get(edge.toNodeId)
    return walk(nextNode)
  }

  return walk(entryNode)
}

// ---------------------------------------------------------------------------
// Controlflow compiler
// ---------------------------------------------------------------------------

function compileControlflow(nodeList, connectionList) {
  if (nodeList.length === 0) return '# (empty graph)\n'

  const idx = buildIndices(nodeList, connectionList)
  const lines = []

  lines.push('## KohakuNodeIR — compiled from node graph')
  lines.push(`## Nodes: ${nodeList.length}   Connections: ${connectionList.length}`)
  lines.push('')

  // Track which nodes have been emitted (shared across all steps)
  const emitted = new Set()

  // ── Step 1: Pure data nodes (no ctrl ports) → variable assignments ─────────
  const dataOnlyNodes = findPureDataNodes(nodeList)
  for (const node of dataOnlyNodes) {
    lines.push(...emitNode(node, idx, 0))
    emitted.add(node.id)
  }
  if (dataOnlyNodes.length > 0) lines.push('')

  // ── Step 2: Disconnected-ctrl nodes → pre-loop @dataflow: block ──────────
  // Nodes that have ctrl ports but NO ctrl connections were inside @dataflow:
  // blocks in the original KIR.  Split them:
  //
  //   • "pre-loop"  — no transitive data dep on any ctrl-connected node.
  //     These are graph-independent initialisation nodes (e.g. to_float).
  //     Emit now as a @dataflow: block before the control flow.
  //
  //   • "in-loop" / "post-loop" — have ctrl-connected data deps.
  //     Collected and emitted at the correct point in steps 6 / 7.
  const disconnectedCtrlNodes = findDisconnectedCtrlNodes(nodeList, idx)

  // Set of all nodes that participate in ctrl flow (have at least one ctrl edge)
  const ctrlConnectedIds = new Set()
  for (const node of nodeList) {
    const hasCtrlIn  = (idx.ctrlInByNode.get(node.id)  ?? []).length > 0
    const hasCtrlOut = (idx.ctrlOutByNode.get(node.id) ?? []).length > 0
    if (hasCtrlIn || hasCtrlOut) ctrlConnectedIds.add(node.id)
  }

  // Returns true if any transitive data dep of `node` is a ctrl-connected node
  function hasCtrlConnectedDataDep(node, visited = new Set()) {
    if (visited.has(node.id)) return false
    visited.add(node.id)
    for (const port of node.dataPorts.inputs) {
      const key  = `${node.id}:${port.id}`
      const edge = idx.dataInEdges.get(key)
      if (!edge) continue
      const srcId = edge.fromNodeId
      if (ctrlConnectedIds.has(srcId)) return true
      const src = idx.nodeMap.get(srcId)
      if (src && hasCtrlConnectedDataDep(src, visited)) return true
    }
    return false
  }

  const preLoopDisconn = disconnectedCtrlNodes.filter(n => !hasCtrlConnectedDataDep(n))

  if (preLoopDisconn.length > 0) {
    const preSet     = new Set(preLoopDisconn.map(n => n.id))
    const topoSorted = topoSortByData(preLoopDisconn, idx, preSet)
    lines.push('@dataflow:')
    for (const node of topoSorted) {
      for (const l of emitNode(node, idx, 1)) lines.push(l)
      emitted.add(node.id)
      lines.push('')
    }
  }

  // ── Step 3: Loop-merge nodes → loop structures ────────────────────────────
  const loopMerges = nodeList.filter(n => n.type === 'merge' && isLoopMerge(n, idx))

  // ── Step 4: Regular ctrl entry nodes (no incoming ctrl) ───────────────────
  // Exclude disconnected-ctrl nodes (they are emitted as @dataflow: blocks in
  // steps 2, 6, or 7 — never as regular ctrl statements).
  const disconnectedCtrlSet = new Set(disconnectedCtrlNodes.map(n => n.id))
  const regularEntries = findEntryNodes(nodeList, idx).filter(
    n => !emitted.has(n.id) && n.type !== 'merge' && !disconnectedCtrlSet.has(n.id)
  )

  const hasAnything =
    dataOnlyNodes.length > 0 || disconnectedCtrlNodes.length > 0 ||
    loopMerges.length > 0 || regularEntries.length > 0

  if (!hasAnything) {
    lines.push('# Warning: no entry point found (no node without incoming control connections)')
    const sorted = [...nodeList].sort((a, b) => a.y - b.y || a.x - b.x)
    lines.push('# ── Nodes (no control flow detected) ──')
    for (const node of sorted) {
      if (emitted.has(node.id)) continue
      lines.push(...emitNode(node, idx, 0))
    }
    return lines.join('\n') + '\n'
  }

  // ── Step 5 + 6: Interleaved: emit pre-loop nodes, then loop structures ──────
  //
  // For each loop merge, determine what the "loop body" entry is.  When the
  // graph comes from a round-tripped KIR import the merge's ctrl output may
  // point back to itself (parser bug), so we fall back to identifying the loop
  // body entry node heuristically:
  //
  //   A regular entry node is the loop body start if its ctrl chain ends at a
  //   branch/switch/parallel that has NO outgoing ctrl connections — indicating
  //   that the back-edge was lost during import.
  //
  // We assign each regular entry node to either:
  //   (a) a loop body (to be emitted indented under the loop label), or
  //   (b) pre-loop code (to be emitted flat before the loop).

  // Build a map: mergeNode.id → loopBodyEntryNode (or null if reachable via ctrl)
  const loopBodyEntryMap = new Map()  // mergeId → entry node (or null)

  for (const mergeNode of loopMerges) {
    const outPort = mergeNode.controlPorts.outputs[0]
    let bodyStartId = null
    if (outPort) {
      const edgeKey = `${mergeNode.id}:${outPort.id}`
      const edge    = idx.ctrlOutEdges.get(edgeKey)
      if (edge && edge.toNodeId !== mergeNode.id) {
        bodyStartId = edge.toNodeId  // properly connected body
      }
    }

    if (!bodyStartId) {
      // Loop body is disconnected — find it among the regular entry nodes.
      // An entry node is the loop body if its ctrl chain terminates (all branch
      // arms have no outgoing ctrl), indicating the back-edge was dropped.
      for (const entry of regularEntries) {
        if (emitted.has(entry.id)) continue
        if (ctrlChainTerminatesOpen(entry, idx)) {
          bodyStartId = entry.id
          break
        }
      }
    }
    loopBodyEntryMap.set(mergeNode.id, bodyStartId)
  }

  // Collect all node IDs that are inside loop bodies
  const loopBodyNodeIds = new Set()
  for (const [mergeId, bodyStartId] of loopBodyEntryMap) {
    if (!bodyStartId) continue
    collectCtrlChain(bodyStartId, idx, loopBodyNodeIds)
  }

  // Separate regular entries into pre-loop and post-loop.
  // Post-loop entries are those not in the loop body AND whose Y position
  // exceeds the loop body's max Y (they come after the loop spatially).
  const loopBodyMaxY = loopBodyNodeIds.size > 0
    ? Math.max(...Array.from(loopBodyNodeIds).map(id => idx.nodeMap.get(id)?.y ?? 0))
    : -Infinity

  const preLoopRegular  = regularEntries.filter(n =>
    !loopBodyNodeIds.has(n.id) && (loopMerges.length === 0 || (n.y ?? 0) <= loopBodyMaxY)
  )
  const postLoopRegular = regularEntries.filter(n =>
    !loopBodyNodeIds.has(n.id) && loopMerges.length > 0 && (n.y ?? 0) > loopBodyMaxY
  )

  // Emit pre-loop regular entry nodes
  for (const entry of preLoopRegular) {
    if (emitted.has(entry.id)) continue
    const chain = walkFromEntry(entry, idx, emitted)
    for (const item of chain) {
      if (item._sentinel === 'loop_start') {
        lines.push(`()jump(\`${item.label}\`)`)
        lines.push(`${item.label}:`)
        continue
      }
      if (item._sentinel === 'loop_merge') {
        emitted.add(item.node.id)
        continue
      }
      if (emitted.has(item.id)) continue
      for (const dep of collectDataDeps(item, idx, emitted)) {
        if (emitted.has(dep.id)) continue
        lines.push(...emitNode(dep, idx, 0, null, emitted))
        emitted.add(dep.id)
      }
      emitted.add(item.id)
      lines.push(...emitNode(item, idx, 0, null, emitted))
    }
    lines.push('')
  }

  // Emit loop merge structures
  for (const mergeNode of loopMerges) {
    if (emitted.has(mergeNode.id)) continue
    const label       = mergeLabel(mergeNode)
    const bodyStartId = loopBodyEntryMap.get(mergeNode.id)

    lines.push(`()jump(\`${label}\`)`)
    lines.push(`${label}:`)
    emitted.add(mergeNode.id)

    if (bodyStartId && !emitted.has(bodyStartId)) {
      const bodyItems = walkLoopBody(mergeNode, bodyStartId, idx, emitted, label)

      for (const item of bodyItems) {
        if (item._sentinel === 'dataflow_group') {
          lines.push('    @dataflow:')
          const groupSet   = new Set(item.nodes.map(n => n.id))
          const topoGroup  = topoSortByData(item.nodes, idx, groupSet)
          for (const dfNode of topoGroup) {
            for (const l of emitNode(dfNode, idx, 2, null, emitted)) lines.push(l)
            emitted.add(dfNode.id)
            lines.push('')
          }
          continue
        }

        if (emitted.has(item.id)) continue
        for (const dep of collectDataDeps(item, idx, emitted)) {
          if (emitted.has(dep.id)) continue
          lines.push(...emitNode(dep, idx, 1, null, emitted))
          emitted.add(dep.id)
        }
        emitted.add(item.id)
        lines.push(...emitNode(item, idx, 1, label, emitted))
      }
    }
    lines.push('')
  }

  // ── Step 7: Emit remaining disconnected-ctrl nodes → @dataflow: block ─────
  // These are the post-loop @dataflow: nodes (to_string, concat, print …).
  const postLoopDisconn = disconnectedCtrlNodes.filter(n => !emitted.has(n.id))
  if (postLoopDisconn.length > 0) {
    const postSet    = new Set(postLoopDisconn.map(n => n.id))
    const topoSorted = topoSortByData(postLoopDisconn, idx, postSet)
    lines.push('@dataflow:')
    for (const node of topoSorted) {
      for (const l of emitNode(node, idx, 1, null, emitted)) lines.push(l)
      emitted.add(node.id)
      lines.push('')
    }
  }

  // ── Step 7b: Emit post-loop regular entry nodes ────────────────────────────
  // These are ctrl-connected nodes that appear after the loop (by Y position).
  for (const entry of postLoopRegular) {
    if (emitted.has(entry.id)) continue
    const chain = walkFromEntry(entry, idx, emitted)
    for (const item of chain) {
      if (item._sentinel === 'loop_start' || item._sentinel === 'loop_merge') continue
      if (emitted.has(item.id)) continue
      for (const dep of collectDataDeps(item, idx, emitted)) {
        if (emitted.has(dep.id)) continue
        lines.push(...emitNode(dep, idx, 0, null, emitted))
        emitted.add(dep.id)
      }
      emitted.add(item.id)
      lines.push(...emitNode(item, idx, 0, null, emitted))
    }
    lines.push('')
  }

  // (No step 8: nodes emitted inside branch/switch/parallel arms are now tracked
  // via the emitted set passed through emitNode, preventing double-emission.)

  return lines.join('\n') + '\n'
}

/**
 * Topologically sort `nodes` by their data-dependency edges.
 * Only considers edges where the source is also in `nodeSet`.
 * Returns nodes in topological order (sources first).
 */
function topoSortByData(nodes, idx, nodeSet) {
  const order   = []
  const visited = new Set()

  function visit(node) {
    if (visited.has(node.id)) return
    visited.add(node.id)
    for (const port of node.dataPorts.inputs) {
      const key  = `${node.id}:${port.id}`
      const edge = idx.dataInEdges.get(key)
      if (!edge || !nodeSet.has(edge.fromNodeId)) continue
      const src = idx.nodeMap.get(edge.fromNodeId)
      if (src) visit(src)
    }
    order.push(node)
  }

  for (const n of nodes) visit(n)
  return order
}

/**
 * Walk the loop body starting from `startNodeId` (the first node after the
 * loop merge's ctrl output edge).  Returns an ordered list of items to emit
 * at the loop-body indentation level.  Items are either node objects or:
 *   { _sentinel: 'dataflow_group', nodes: [...] }  — an in-loop @dataflow: block
 */
function walkLoopBody(mergeNode, startNodeId, idx, emitted, loopLabel) {
  const ctrlChain = []
  const visited   = new Set([mergeNode.id])

  // Walk ctrl chain from startNodeId until we hit a merge or dead end.
  function walk(nodeId) {
    if (!nodeId || visited.has(nodeId)) return
    visited.add(nodeId)

    const node = idx.nodeMap.get(nodeId)
    if (!node) return

    if (node.type === 'merge') return

    ctrlChain.push(node)

    if (node.type === 'branch' || node.type === 'switch' || node.type === 'parallel') {
      const mergeAfter = findMergeAfter(node, idx)
      if (mergeAfter && mergeAfter.id !== mergeNode.id) {
        visited.add(mergeAfter.id)
        const outPort = mergeAfter.controlPorts.outputs[0]
        if (outPort) {
          const edgeKey = `${mergeAfter.id}:${outPort.id}`
          const edge    = idx.ctrlOutEdges.get(edgeKey)
          if (edge && edge.toNodeId !== mergeAfter.id) walk(edge.toNodeId)
        }
      }
      return
    }

    const outPort = node.controlPorts.outputs[0]
    if (!outPort) return
    const edgeKey = `${node.id}:${outPort.id}`
    const edge    = idx.ctrlOutEdges.get(edgeKey)
    if (!edge || edge.toNodeId === node.id) return
    walk(edge.toNodeId)
  }

  walk(startNodeId)

  if (ctrlChain.length === 0) return []

  // Determine the Y-range of the loop body ctrl chain.
  const bodyYMin = Math.min(...ctrlChain.map(n => n.y ?? 0))
  const bodyYMax = Math.max(...ctrlChain.map(n => n.y ?? 0))

  // Collect disconnected-ctrl nodes that are NOT yet emitted globally AND whose
  // Y position falls within the loop body's Y range.  These are in-loop
  // @dataflow: candidates (e.g. multiply, add between counter-update and
  // less_than in a loop body).
  const inLoopDisconn = Array.from(idx.nodeMap.values()).filter(n => {
    if (emitted.has(n.id)) return false
    if (n.controlPorts.inputs.length === 0 && n.controlPorts.outputs.length === 0) return false
    const hasCtrlIn  = (idx.ctrlInByNode.get(n.id)  ?? []).length > 0
    const hasCtrlOut = (idx.ctrlOutByNode.get(n.id) ?? []).length > 0
    if (hasCtrlIn || hasCtrlOut) return false
    const ny = n.y ?? 0
    return ny >= bodyYMin && ny <= bodyYMax
  })

  // Build the final item list by interleaving ctrl nodes and @dataflow: groups.
  // We insert an @dataflow: group before the first ctrl node whose Y position
  // exceeds the dataflow nodes' Y positions (i.e. place dataflow nodes at the
  // right point in the sequence by Y ordering).
  //
  // Simple strategy: sort all items (ctrl + in-loop dataflow) by Y position and
  // then build groups: consecutive disconnected-ctrl nodes form a @dataflow: block.

  const allBodyItems = [
    ...ctrlChain.map(n => ({ kind: 'ctrl', node: n, y: n.y ?? 0 })),
    ...inLoopDisconn.map(n => ({ kind: 'df',   node: n, y: n.y ?? 0 })),
  ].sort((a, b) => a.y - b.y || 0)

  const finalItems  = []
  let dfBuffer = []

  function flushDfBuffer() {
    if (dfBuffer.length === 0) return
    const nodeSet = new Set(dfBuffer.map(n => n.id))
    finalItems.push({ _sentinel: 'dataflow_group', nodes: topoSortByData(dfBuffer, idx, nodeSet) })
    dfBuffer = []
  }

  for (const item of allBodyItems) {
    if (item.kind === 'df') {
      dfBuffer.push(item.node)
    } else {
      // ctrl node — flush any pending dataflow group first, then emit the ctrl node
      flushDfBuffer()
      finalItems.push(item.node)
    }
  }
  // Any remaining dataflow items (after the last ctrl node) — still emit them
  // inside the loop body (they'll be placed after the last ctrl node, which is
  // usually the branch, so they won't appear after it in practice).
  flushDfBuffer()

  return finalItems
}

/**
 * Gather the transitive data-dep nodes of `node` that are in `candidatePool`
 * (disconnected-ctrl nodes) and not yet emitted (not in `bodyEmitted`).
 * Returns them in topological order.
 */
/**
 * Walk from an entry node following control flow, collecting all nodes in order.
 * Items in the result array are either node objects or special sentinel objects:
 *   { _sentinel: 'loop_start', label }  — emit `()jump(\`label\`)` then `label:`
 *   { _sentinel: 'loop_merge', node }   — the merge node itself (already labeled above)
 */
function walkFromEntry(entryNode, idx, emitted) {
  const result  = []
  const visited = new Set()

  function walk(node) {
    if (!node || visited.has(node.id)) return
    visited.add(node.id)

    if (node.type === 'merge') {
      if (isLoopMerge(node, idx)) {
        const label = mergeLabel(node)
        result.push({ _sentinel: 'loop_start', label })
        result.push({ _sentinel: 'loop_merge', node })
        const outPort = node.controlPorts.outputs[0]
        if (outPort) {
          const edgeKey = `${node.id}:${outPort.id}`
          const edge    = idx.ctrlOutEdges.get(edgeKey)
          if (edge && edge.toNodeId !== node.id) {
            const nextNode = idx.nodeMap.get(edge.toNodeId)
            if (nextNode) walk(nextNode)
          }
        }
      } else {
        // Convergence merge — skip node, continue from its output
        const outPort = node.controlPorts.outputs[0]
        if (outPort) {
          const edgeKey = `${node.id}:${outPort.id}`
          const edge    = idx.ctrlOutEdges.get(edgeKey)
          if (edge) {
            const nextNode = idx.nodeMap.get(edge.toNodeId)
            if (nextNode) walk(nextNode)
          }
        }
      }
      return
    }

    result.push(node)

    if (node.type === 'branch' || node.type === 'switch' || node.type === 'parallel') {
      const mergeNode = findMergeAfter(node, idx)
      if (mergeNode) walk(mergeNode)
      return
    }

    const outPort = node.controlPorts.outputs[0]
    if (!outPort) return
    const edgeKey = `${node.id}:${outPort.id}`
    const edge    = idx.ctrlOutEdges.get(edgeKey)
    if (!edge) return
    const nextNode = idx.nodeMap.get(edge.toNodeId)
    if (nextNode) walk(nextNode)
  }

  walk(entryNode)
  return result
}

// ---------------------------------------------------------------------------
// Dataflow compiler
// ---------------------------------------------------------------------------

function compileDataflow(nodeList, connectionList) {
  if (nodeList.length === 0) return '@mode dataflow\n\n# (empty graph)\n'

  const idx = buildIndices(nodeList, connectionList)
  const lines = []

  lines.push('@mode dataflow')
  lines.push('')
  lines.push('## KohakuNodeIR — dataflow mode')
  lines.push(`## Nodes: ${nodeList.length}   Connections: ${connectionList.length}`)
  lines.push('')

  // In dataflow mode, we just list all nodes. The backend handles topological sort.
  // Sort by position as a hint (top-left first).
  const sorted = [...nodeList].sort((a, b) => a.y - b.y || a.x - b.x)

  for (const node of sorted) {
    lines.push(emitMeta(node, 0))

    if (node.type === 'value') {
      // Emit as assignment
      const outPort = node.dataPorts.outputs[0]
      if (outPort) {
        const vn = outputVarName(node, outPort.name)
        let val = 'None'
        if (node.properties?.value !== undefined) {
          val = formatLiteral(node.properties.value, node.properties?.valueType)
        }
        lines.push(`${vn} = ${val}`)
      }
    } else {
      // Emit as function call
      const funcName = sanitizeIdent(node.type)
      const inputArgs = node.dataPorts.inputs.map(port => resolveInput(node, port, idx))
      const outputVars = node.dataPorts.outputs.map(port => outputVarName(node, port.name))
      lines.push(`(${inputArgs.join(', ')})${funcName}(${outputVars.join(', ')})`)
    }
    lines.push('')
  }

  return lines.join('\n') + '\n'
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Compile the graph into .kir IR text.
 *
 * @param {Array} nodeList - Array of node objects from graph store
 * @param {Array} connectionList - Array of connection objects from graph store
 * @param {'controlflow'|'dataflow'} mode - Compilation mode
 * @returns {{ ir: string, errors: string[] }} The compiled IR text and any errors/warnings
 */
export function compileGraph(nodeList, connectionList, mode = 'controlflow') {
  const errors = []

  try {
    let ir
    if (mode === 'dataflow') {
      ir = compileDataflow(nodeList, connectionList)
    } else {
      ir = compileControlflow(nodeList, connectionList)
    }
    return { ir, errors }
  } catch (err) {
    errors.push(`Compilation error: ${err.message}`)
    return {
      ir: `# Compilation failed\n# ${err.message}\n`,
      errors,
    }
  }
}

export default compileGraph

// ---------------------------------------------------------------------------
// Kirgraph pipeline (L1 → L2)
// ---------------------------------------------------------------------------

/**
 * Convert graph store state → .kirgraph → .kir text.
 * This is the proper L1 → L2 pipeline.
 *
 * @param {object[]} nodeList
 * @param {object[]} connectionList
 * @returns {string} KIR text
 */
export function compileViaKirgraph(nodeList, connectionList) {
  const kirgraph = graphToKirgraph(nodeList, connectionList)
  return compileKirgraphToKir(kirgraph)
}

/**
 * Compile a .kirgraph object directly to .kir text.
 * This is the L1 → L2 compiler working from the kirgraph format.
 *
 * The algorithm mirrors the existing controlflow compiler but works from the
 * normalised KGNode / KGEdge structures instead of the raw graph store format.
 *
 * @param {{ version: string, nodes: object[], edges: object[] }} kirgraph
 * @returns {string} KIR text
 */
export function compileKirgraphToKir(kirgraph) {
  const kgNodes = kirgraph.nodes ?? []
  const kgEdges = kirgraph.edges ?? []

  if (kgNodes.length === 0) return '# (empty graph)\n'

  // ---- Build indices from kirgraph ----------------------------------------

  /** @type {Map<string, object>} nodeId -> KGNode */
  const nodeMap = new Map()
  for (const n of kgNodes) nodeMap.set(n.id, n)

  // Control edge adjacency
  // key: "fromNodeId:fromPortName" -> { toNodeId, toPortName }
  const ctrlOutEdges  = new Map()
  // key: "toNodeId:toPortName" -> { fromNodeId, fromPortName }
  const ctrlInEdges   = new Map()
  // nodeId -> [edge, ...]
  const ctrlInByNode  = new Map()
  const ctrlOutByNode = new Map()

  // Data edge adjacency
  // key: "toNodeId:toPortName" -> { fromNodeId, fromPortName }
  const dataInEdges   = new Map()

  for (const edge of kgEdges) {
    if (edge.type === 'control') {
      const outKey = `${edge.from.node}:${edge.from.port}`
      ctrlOutEdges.set(outKey, { toNodeId: edge.to.node, toPortName: edge.to.port })

      const inKey = `${edge.to.node}:${edge.to.port}`
      ctrlInEdges.set(inKey, { fromNodeId: edge.from.node, fromPortName: edge.from.port })

      if (!ctrlInByNode.has(edge.to.node)) ctrlInByNode.set(edge.to.node, [])
      ctrlInByNode.get(edge.to.node).push(edge)

      if (!ctrlOutByNode.has(edge.from.node)) ctrlOutByNode.set(edge.from.node, [])
      ctrlOutByNode.get(edge.from.node).push(edge)
    } else {
      const inKey = `${edge.to.node}:${edge.to.port}`
      dataInEdges.set(inKey, { fromNodeId: edge.from.node, fromPortName: edge.from.port })
    }
  }

  const kgIdx = { nodeMap, ctrlOutEdges, ctrlInEdges, ctrlInByNode, ctrlOutByNode, dataInEdges }

  // ---- Loop merge detection (kirgraph) ------------------------------------

  function kgMergeLabel(kgNode) {
    const cleanId = kgNode.id.replace(/[^a-zA-Z0-9_]/g, '_').toLowerCase()
    return `loop_${cleanId}`
  }

  function kgIsLoopMerge(kgNode) {
    // Forward reachability from the merge node using ctrl edges
    const reachable = new Set()
    const stack = [kgNode.id]
    while (stack.length > 0) {
      const id = stack.pop()
      if (reachable.has(id)) continue
      reachable.add(id)
      for (const edge of (ctrlOutByNode.get(id) ?? [])) {
        if (!reachable.has(edge.to.node)) stack.push(edge.to.node)
      }
    }
    // A back-edge exists if any ctrl input of the merge comes from a reachable node
    for (const edge of (ctrlInByNode.get(kgNode.id) ?? [])) {
      if (reachable.has(edge.from.node)) return true
    }
    return false
  }

  // ---- Variable naming -----------------------------------------------------

  // In kirgraph the node id is already a clean semantic id (e.g. "add1", "val_a").
  // Variable name: {nodeId}_{portName} (sanitised), matching the spec §5.1.
  function kgVarName(nodeId, portName) {
    const cleanId   = nodeId.replace(/[^a-zA-Z0-9_]/g, '_')
    const cleanPort = portName.replace(/[^a-zA-Z0-9_]/g, '_')
    return `${cleanId}_${cleanPort}`
  }

  // ---- Data input resolution -----------------------------------------------

  function kgResolveInput(kgNode, inputPort) {
    // inputPort is { port, type, default? }
    const key = `${kgNode.id}:${inputPort.port}`
    const edge = dataInEdges.get(key)

    if (edge) {
      // Variable produced by the source node's output port
      return kgVarName(edge.fromNodeId, edge.fromPortName)
    }

    // Not connected — use default value
    if (inputPort.default !== undefined && inputPort.default !== null) {
      return formatLiteral(inputPort.default, inputPort.type)
    }

    return 'None'
  }

  // ---- Meta emission -------------------------------------------------------

  function kgEmitMeta(kgNode, indent) {
    const pad = '    '.repeat(indent)
    const pos = kgNode.meta?.pos ?? [0, 0]
    return `${pad}@meta node_id="${kgNode.id}" pos=(${pos[0]}, ${pos[1]})`
  }

  // ---- Node statement emission ---------------------------------------------

  function kgEmitNode(kgNode, indent) {
    const pad   = '    '.repeat(indent)
    const lines = []
    lines.push(kgEmitMeta(kgNode, indent))

    switch (kgNode.type) {
      case 'value':
        lines.push(...kgEmitValueNode(kgNode, pad))
        break
      case 'branch':
        lines.push(...kgEmitBranchNode(kgNode, pad, indent))
        break
      case 'switch':
        lines.push(...kgEmitSwitchNode(kgNode, pad, indent))
        break
      case 'parallel':
        lines.push(...kgEmitParallelNode(kgNode, pad, indent))
        break
      case 'merge':
        lines.push(`${pad}# merge point`)
        break
      default:
        lines.push(...kgEmitFunctionNode(kgNode, pad))
        break
    }

    return lines
  }

  function kgEmitValueNode(kgNode, pad) {
    const outPort = (kgNode.data_outputs ?? [])[0]
    if (!outPort) return [`${pad}# value node with no output port`]

    const vn  = kgVarName(kgNode.id, outPort.port)
    const val = kgNode.properties?.value !== undefined
      ? formatLiteral(kgNode.properties.value, kgNode.properties?.value_type)
      : 'None'

    return [`${pad}${vn} = ${val}`]
  }

  function kgEmitFunctionNode(kgNode, pad) {
    const funcName  = sanitizeIdent(kgNode.type)
    const inputArgs = (kgNode.data_inputs ?? []).map(p => kgResolveInput(kgNode, p))
    const outVars   = (kgNode.data_outputs ?? []).map(p => kgVarName(kgNode.id, p.port))
    return [`${pad}(${inputArgs.join(', ')})${funcName}(${outVars.join(', ')})`]
  }

  function kgEmitBranchNode(kgNode, pad, indent) {
    const lines = []
    const condPort = (kgNode.data_inputs ?? [])[0]
    const condExpr = condPort ? kgResolveInput(kgNode, condPort) : 'False'

    const truePortName  = (kgNode.ctrl_outputs ?? []).find(n => n === 'true' || n.toLowerCase().includes('true'))
      ?? (kgNode.ctrl_outputs ?? [])[0] ?? 'true'
    const falsePortName = (kgNode.ctrl_outputs ?? []).find(n => n === 'false' || n.toLowerCase().includes('false'))
      ?? (kgNode.ctrl_outputs ?? [])[1] ?? 'false'

    const trueNs  = nsLabel(`br_${kgNode.id}_true`)
    const falseNs = nsLabel(`br_${kgNode.id}_false`)

    lines.push(`${pad}(${condExpr})branch(\`${trueNs}\`, \`${falseNs}\`)`)

    const { chain: trueChain, loopJumpLabel: trueJump } = kgWalkControlChain(kgNode.id, truePortName, kgIdx)
    lines.push(`${pad}${trueNs}:`)
    if (trueChain.length > 0) {
      for (const n of trueChain) lines.push(...kgEmitNode(n, indent + 1))
    } else if (!trueJump) {
      lines.push(`${pad}    # (empty branch)`)
    }
    if (trueJump) lines.push(`${pad}    ()jump(\`${trueJump}\`)`)

    const { chain: falseChain, loopJumpLabel: falseJump } = kgWalkControlChain(kgNode.id, falsePortName, kgIdx)
    lines.push(`${pad}${falseNs}:`)
    if (falseChain.length > 0) {
      for (const n of falseChain) lines.push(...kgEmitNode(n, indent + 1))
    } else if (!falseJump) {
      lines.push(`${pad}    # (empty branch)`)
    }
    if (falseJump) lines.push(`${pad}    ()jump(\`${falseJump}\`)`)

    return lines
  }

  function kgEmitSwitchNode(kgNode, pad, indent) {
    const lines = []
    const valPort = (kgNode.data_inputs ?? [])[0]
    const valExpr = valPort ? kgResolveInput(kgNode, valPort) : 'None'

    const cases = (kgNode.ctrl_outputs ?? []).map(portName => {
      const caseNs  = nsLabel(`sw_${kgNode.id}_${sanitizeIdent(portName)}`)
      const numMatch = portName.match(/(\d+)/)
      const caseVal  = numMatch ? numMatch[1] : `"${portName}"`
      return { portName, caseNs, caseVal }
    })

    const caseArgs = cases.map(c => `${c.caseVal}=>\`${c.caseNs}\``).join(', ')
    lines.push(`${pad}(${valExpr})switch(${caseArgs})`)

    for (const c of cases) {
      const { chain, loopJumpLabel } = kgWalkControlChain(kgNode.id, c.portName, kgIdx)
      lines.push(`${pad}${c.caseNs}:`)
      if (chain.length > 0) {
        for (const n of chain) lines.push(...kgEmitNode(n, indent + 1))
      } else if (!loopJumpLabel) {
        lines.push(`${pad}    # (empty case)`)
      }
      if (loopJumpLabel) lines.push(`${pad}    ()jump(\`${loopJumpLabel}\`)`)
    }

    return lines
  }

  function kgEmitParallelNode(kgNode, pad, indent) {
    const lines   = []
    const branches = (kgNode.ctrl_outputs ?? []).map((portName, i) => ({
      portName,
      ns: nsLabel(`par_${kgNode.id}_${i}`),
    }))

    const nsArgs = branches.map(b => `\`${b.ns}\``).join(', ')
    lines.push(`${pad}()parallel(${nsArgs})`)

    for (const b of branches) {
      const { chain, loopJumpLabel } = kgWalkControlChain(kgNode.id, b.portName, kgIdx)
      lines.push(`${pad}${b.ns}:`)
      if (chain.length > 0) {
        for (const n of chain) lines.push(...kgEmitNode(n, indent + 1))
      } else if (!loopJumpLabel) {
        lines.push(`${pad}    # (empty parallel branch)`)
      }
      if (loopJumpLabel) lines.push(`${pad}    ()jump(\`${loopJumpLabel}\`)`)
    }

    return lines
  }

  // ---- Control chain walking -----------------------------------------------

  function kgWalkControlChain(fromNodeId, fromPortName, kgIdx) {
    const chain   = []
    const visited = new Set()
    let curNodeId   = fromNodeId
    let curPortName = fromPortName

    while (true) {
      const edgeKey = `${curNodeId}:${curPortName}`
      const edge    = kgIdx.ctrlOutEdges.get(edgeKey)
      if (!edge) break

      const nextNode = kgIdx.nodeMap.get(edge.toNodeId)
      if (!nextNode || visited.has(nextNode.id)) break
      visited.add(nextNode.id)

      if (nextNode.type === 'merge') {
        if (kgIsLoopMerge(nextNode)) {
          return { chain, loopJumpLabel: kgMergeLabel(nextNode) }
        }
        break
      }

      chain.push(nextNode)

      if (nextNode.type === 'branch' || nextNode.type === 'switch' || nextNode.type === 'parallel') {
        const mergeNode = kgFindMergeAfter(nextNode, kgIdx)
        if (mergeNode) {
          if (kgIsLoopMerge(mergeNode)) {
            return { chain, loopJumpLabel: kgMergeLabel(mergeNode) }
          }
          const mergeOutName = (mergeNode.ctrl_outputs ?? [])[0]
          if (mergeOutName) {
            curNodeId   = mergeNode.id
            curPortName = mergeOutName
            continue
          }
        }
        break
      }

      const outPortName = (nextNode.ctrl_outputs ?? [])[0]
      if (!outPortName) break

      curNodeId   = nextNode.id
      curPortName = outPortName
    }

    return { chain, loopJumpLabel: null }
  }

  function kgFindMergeAfter(branchingNode, kgIdx) {
    const visited = new Set()

    function walk(nodeId, portName, depth) {
      if (depth > 100) return null
      const edge = kgIdx.ctrlOutEdges.get(`${nodeId}:${portName}`)
      if (!edge) return null

      const next = kgIdx.nodeMap.get(edge.toNodeId)
      if (!next) return null
      if (next.type === 'merge') return next
      if (visited.has(next.id)) return null
      visited.add(next.id)

      if (next.type === 'branch' || next.type === 'switch' || next.type === 'parallel') {
        const inner = kgFindMergeAfter(next, kgIdx)
        if (inner) {
          const innerOut = (inner.ctrl_outputs ?? [])[0]
          if (innerOut) return walk(inner.id, innerOut, depth + 1)
        }
        return null
      }

      const out = (next.ctrl_outputs ?? [])[0]
      if (!out) return null
      return walk(next.id, out, depth + 1)
    }

    for (const portName of (branchingNode.ctrl_outputs ?? [])) {
      const m = walk(branchingNode.id, portName, 0)
      if (m) return m
    }
    return null
  }

  // ---- Partition nodes -------------------------------------------------------

  // Pure data nodes: no ctrl_inputs and no ctrl_outputs
  const pureDataNodes = kgNodes.filter(n =>
    (n.ctrl_inputs  ?? []).length === 0 &&
    (n.ctrl_outputs ?? []).length === 0
  )

  // Ctrl-connected nodes with no incoming ctrl edges (entry points)
  const entryNodes = kgNodes.filter(n => {
    const hasCtrl = (n.ctrl_inputs ?? []).length > 0 || (n.ctrl_outputs ?? []).length > 0
    if (!hasCtrl) return false
    const incoming = ctrlInByNode.get(n.id)
    return !incoming || incoming.length === 0
  }).sort((a, b) => {
    const pa = a.meta?.pos ?? [0, 0]
    const pb = b.meta?.pos ?? [0, 0]
    return pa[1] - pb[1] || pa[0] - pb[0]
  })

  // ---- Emit ---------------------------------------------------------------

  const lines = []
  lines.push('## KohakuNodeIR — compiled via kirgraph')
  lines.push(`## Nodes: ${kgNodes.length}   Edges: ${kgEdges.length}`)
  lines.push('')

  if (pureDataNodes.length > 0) {
    lines.push('@dataflow:')
    for (const n of pureDataNodes) {
      for (const l of kgEmitNode(n, 1)) lines.push(l)
      lines.push('')
    }
  }

  if (entryNodes.length > 0) {
    const emitted = new Set(pureDataNodes.map(n => n.id))

    for (const entry of entryNodes) {
      if (emitted.has(entry.id)) continue

      // Walk from this entry collecting all nodes in ctrl order.
      // Items may be node objects or sentinels:
      //   { _sentinel: 'loop_start', label }  — emit jump + label
      //   { _sentinel: 'loop_merge', node }   — skip (label already emitted)
      const visited2 = new Set()
      function walkEntry(node) {
        if (!node || visited2.has(node.id)) return []
        visited2.add(node.id)

        if (node.type === 'merge') {
          if (kgIsLoopMerge(node)) {
            const label = kgMergeLabel(node)
            const result = [
              { _sentinel: 'loop_start', label },
              { _sentinel: 'loop_merge', node },
            ]
            const mOut = (node.ctrl_outputs ?? [])[0]
            if (mOut) {
              const nextEdge = ctrlOutEdges.get(`${node.id}:${mOut}`)
              if (nextEdge) {
                const nextNode = nodeMap.get(nextEdge.toNodeId)
                result.push(...walkEntry(nextNode))
              }
            }
            return result
          }
          // Convergence merge — continue without emitting a label
          const mOut = (node.ctrl_outputs ?? [])[0]
          if (!mOut) return []
          const nextEdge = ctrlOutEdges.get(`${node.id}:${mOut}`)
          if (!nextEdge) return []
          const nextNode = nodeMap.get(nextEdge.toNodeId)
          return walkEntry(nextNode)
        }

        const result = [node]

        if (node.type === 'branch' || node.type === 'switch' || node.type === 'parallel') {
          const merge = kgFindMergeAfter(node, kgIdx)
          if (merge) {
            result.push(...walkEntry(merge))
          }
          return result
        }

        const outPort = (node.ctrl_outputs ?? [])[0]
        if (!outPort) return result
        const nextEdge = ctrlOutEdges.get(`${node.id}:${outPort}`)
        if (!nextEdge) return result
        const nextNode = nodeMap.get(nextEdge.toNodeId)
        result.push(...walkEntry(nextNode))
        return result
      }

      const chain = walkEntry(entry)
      for (const item of chain) {
        if (item._sentinel === 'loop_start') {
          lines.push(`()jump(\`${item.label}\`)`)
          lines.push(`${item.label}:`)
          continue
        }
        if (item._sentinel === 'loop_merge') {
          emitted.add(item.node.id)
          continue
        }
        if (emitted.has(item.id)) continue
        emitted.add(item.id)
        for (const l of kgEmitNode(item, 0)) lines.push(l)
        lines.push('')
      }
    }
  } else if (pureDataNodes.length === 0) {
    // Nothing was organised — fall back to position-sorted emit
    lines.push('# Warning: no control flow entry point found')
    const sorted = [...kgNodes].sort((a, b) => {
      const pa = a.meta?.pos ?? [0, 0]
      const pb = b.meta?.pos ?? [0, 0]
      return pa[1] - pb[1] || pa[0] - pb[0]
    })
    for (const n of sorted) {
      for (const l of kgEmitNode(n, 0)) lines.push(l)
      lines.push('')
    }
  }

  return lines.join('\n') + '\n'
}
