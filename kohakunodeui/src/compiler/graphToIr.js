/**
 * graphToIr.js — Graph-to-KIR compiler
 *
 * Converts the graph store state (nodes + connections) into valid .kir IR text.
 * Supports both controlflow and dataflow compilation modes.
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Shorten a node ID for use in variable names.
 * Takes the first 8 chars after the "node-" prefix, or the first 8 chars.
 */
function shortId(nodeId) {
  const stripped = nodeId.replace(/^node-/, '')
  return stripped.slice(0, 8).replace(/-/g, '_')
}

/**
 * Build a valid KIR variable name for a data output port.
 */
function varName(nodeId, portName) {
  const clean = portName.replace(/[^a-zA-Z0-9_]/g, '_')
  return `v_${shortId(nodeId)}_${clean}`
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
    return varName(srcNode.id, srcPort.name)
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
 */
function emitNode(node, idx, indent) {
  const pad = '    '.repeat(indent)
  const lines = []

  // Always emit metadata
  lines.push(emitMeta(node, indent))

  switch (node.type) {
    case 'value':
      lines.push(...emitValueNode(node, idx, pad))
      break
    case 'branch':
      lines.push(...emitBranchNode(node, idx, pad, indent))
      break
    case 'switch':
      lines.push(...emitSwitchNode(node, idx, pad, indent))
      break
    case 'merge':
      // Merge is handled structurally — it's a namespace label / convergence point.
      // When encountered in a walk, we just emit a comment.
      lines.push(`${pad}# merge point`)
      break
    case 'parallel':
      lines.push(...emitParallelNode(node, idx, pad, indent))
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

  const vn = varName(node.id, outPort.name)

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
  const outputVars = node.dataPorts.outputs.map(port => varName(node.id, port.name))

  // If no outputs, use empty parens
  const inputStr = inputArgs.join(', ')
  const outputStr = outputVars.join(', ')

  return [`${pad}(${inputStr})${funcName}(${outputStr})`]
}

/**
 * Branch node: `(condition)branch(\`true_ns\`, \`false_ns\`)`
 * Then emit the two branch namespaces by walking control outputs.
 */
function emitBranchNode(node, idx, pad, indent) {
  const lines = []

  // Resolve the condition input
  const condPort = node.dataPorts.inputs[0]
  const condExpr = condPort ? resolveInput(node, condPort, idx) : 'False'

  // Find the control output ports (true and false)
  const truePort = node.controlPorts.outputs.find(p =>
    p.name === 'true' || p.name.toLowerCase().includes('true')
  ) || node.controlPorts.outputs[0]

  const falsePort = node.controlPorts.outputs.find(p =>
    p.name === 'false' || p.name.toLowerCase().includes('false')
  ) || node.controlPorts.outputs[1]

  const trueNs = nsLabel(`br_${shortId(node.id)}_true`)
  const falseNs = nsLabel(`br_${shortId(node.id)}_false`)

  lines.push(`${pad}(${condExpr})branch(\`${trueNs}\`, \`${falseNs}\`)`)

  // Emit true namespace
  if (truePort) {
    const trueChain = walkControlChain(node.id, truePort.id, idx)
    lines.push(`${pad}${trueNs}:`)
    if (trueChain.length > 0) {
      for (const chainNode of trueChain) {
        lines.push(...emitNode(chainNode, idx, indent + 1))
      }
    } else {
      lines.push(`${pad}    # (empty branch)`)
    }
  }

  // Emit false namespace
  if (falsePort) {
    const falseChain = walkControlChain(node.id, falsePort.id, idx)
    lines.push(`${pad}${falseNs}:`)
    if (falseChain.length > 0) {
      for (const chainNode of falseChain) {
        lines.push(...emitNode(chainNode, idx, indent + 1))
      }
    } else {
      lines.push(`${pad}    # (empty branch)`)
    }
  }

  return lines
}

/**
 * Switch node: `(value)switch(case0=>\`ns0\`, case1=>\`ns1\`, ...)`
 */
function emitSwitchNode(node, idx, pad, indent) {
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
    const chain = walkControlChain(node.id, c.ctrlOut.id, idx)
    lines.push(`${pad}${c.caseNs}:`)
    if (chain.length > 0) {
      for (const chainNode of chain) {
        lines.push(...emitNode(chainNode, idx, indent + 1))
      }
    } else {
      lines.push(`${pad}    # (empty case)`)
    }
  }

  return lines
}

/**
 * Parallel node: `()parallel(\`ns0\`, \`ns1\`, ...)`
 */
function emitParallelNode(node, idx, pad, indent) {
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
    const chain = walkControlChain(node.id, b.ctrlOut.id, idx)
    lines.push(`${pad}${b.branchNs}:`)
    if (chain.length > 0) {
      for (const chainNode of chain) {
        lines.push(...emitNode(chainNode, idx, indent + 1))
      }
    } else {
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
 * Returns an ordered array of nodes to emit.
 * Stops at merge nodes (which have multiple ctrl inputs), or when there's
 * no next node.
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

    // Avoid infinite loops
    if (visited.has(nextNode.id)) break
    visited.add(nextNode.id)

    // If this node is a merge and has multiple ctrl inputs, it is a convergence
    // point. Stop the chain here — the merge will be handled at a higher level.
    if (nextNode.type === 'merge') {
      // Don't include the merge in this sub-chain; it belongs to the parent scope
      break
    }

    chain.push(nextNode)

    // Find the "out" control port to continue walking.
    // For branch/switch/parallel, the sub-chains are emitted inside emitNode,
    // so we need to find the continuation AFTER those sub-chains.
    // For branch/switch/parallel nodes, there is no single "out" — they fan out.
    // The continuation is handled by the merge node detection above.
    if (nextNode.type === 'branch' || nextNode.type === 'switch' || nextNode.type === 'parallel') {
      // These nodes handle their own sub-chains internally.
      // After a branch/switch/parallel, we look for a merge node that
      // gathers the control outputs. We need to find it and continue from there.
      const mergeNode = findMergeAfter(nextNode, idx)
      if (mergeNode) {
        // Continue from the merge node's output
        const mergeOutPort = mergeNode.controlPorts.outputs[0]
        if (mergeOutPort) {
          currentNodeId = mergeNode.id
          currentPortId = mergeOutPort.id
          continue
        }
      }
      // No merge found — end of this chain
      break
    }

    // For regular nodes, follow the first control output
    const outPort = nextNode.controlPorts.outputs[0]
    if (!outPort) break

    currentNodeId = nextNode.id
    currentPortId = outPort.id
  }

  return chain
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

  // 1. Emit pure data nodes (value nodes, no control ports) as variable assignments
  const dataOnlyNodes = findPureDataNodes(nodeList)
  if (dataOnlyNodes.length > 0) {
    lines.push('# ── Data declarations ──')
    for (const node of dataOnlyNodes) {
      lines.push(...emitNode(node, idx, 0))
    }
    lines.push('')
  }

  // 2. Find entry points and walk control flow
  const entryNodes = findEntryNodes(nodeList, idx)

  if (entryNodes.length === 0 && dataOnlyNodes.length === 0) {
    lines.push('# Warning: no entry point found (no node without incoming control connections)')
    // Fall back: emit all nodes in y-sorted order
    const sorted = [...nodeList].sort((a, b) => a.y - b.y || a.x - b.x)
    lines.push('# ── Nodes (no control flow detected) ──')
    for (const node of sorted) {
      lines.push(...emitNode(node, idx, 0))
    }
  } else if (entryNodes.length > 0) {
    lines.push('# ── Control flow ──')
    // Track which nodes have been emitted to avoid duplicates
    const emitted = new Set()
    // Mark data-only nodes as already emitted
    for (const n of dataOnlyNodes) emitted.add(n.id)

    for (const entry of entryNodes) {
      if (emitted.has(entry.id)) continue
      // Walk from this entry point
      const chain = walkFromEntry(entry, idx, emitted)
      for (const node of chain) {
        if (emitted.has(node.id)) continue
        emitted.add(node.id)
        lines.push(...emitNode(node, idx, 0))
      }
      lines.push('')
    }
  }

  return lines.join('\n') + '\n'
}

/**
 * Walk from an entry node following control flow, collecting all nodes in order.
 */
function walkFromEntry(entryNode, idx, emitted) {
  const result = []
  const visited = new Set()

  function walk(node) {
    if (!node || visited.has(node.id)) return
    visited.add(node.id)
    result.push(node)

    // For branch/switch/parallel: the sub-chains are emitted inside emitNode.
    // We need to find the merge node and continue from there.
    if (node.type === 'branch' || node.type === 'switch' || node.type === 'parallel') {
      const mergeNode = findMergeAfter(node, idx)
      if (mergeNode) {
        const mergeOut = mergeNode.controlPorts.outputs[0]
        if (mergeOut) {
          // Continue from merge output
          const edgeKey = `${mergeNode.id}:${mergeOut.id}`
          const edge = idx.ctrlOutEdges.get(edgeKey)
          if (edge) {
            const nextNode = idx.nodeMap.get(edge.toNodeId)
            if (nextNode) walk(nextNode)
          }
        }
      }
      return
    }

    // For merge nodes: just continue from their output
    // (merge nodes encountered during a top-level walk mean they're
    // convergence points that aren't part of a branch sub-chain)

    // Regular or merge node: follow the first control output
    const outPort = node.controlPorts.outputs[0]
    if (!outPort) return

    const edgeKey = `${node.id}:${outPort.id}`
    const edge = idx.ctrlOutEdges.get(edgeKey)
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
        const vn = varName(node.id, outPort.name)
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
      const outputVars = node.dataPorts.outputs.map(port => varName(node.id, port.name))
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
