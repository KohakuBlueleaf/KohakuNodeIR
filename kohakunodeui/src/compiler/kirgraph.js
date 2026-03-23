/**
 * kirgraph.js — Graph store ↔ .kirgraph format converters
 *
 * Graph store port shape:
 *   { id: string, name: string, dataType?: string, defaultValue?: any }
 *
 * KGNode data port shape:
 *   { port: string, type: string, default?: any }
 *
 * KGNode ctrl port shape: string (port name)
 *
 * Connection shape in graph store:
 *   { id, fromNodeId, fromPortId, toNodeId, toPortId, portType: 'data'|'control' }
 *
 * KGEdge shape:
 *   { type: 'data'|'control', from: { node, port }, to: { node, port } }
 */

// ---------------------------------------------------------------------------
// graphToKirgraph
// ---------------------------------------------------------------------------

/**
 * Export the current graph store state to .kirgraph format.
 *
 * @param {object[]} nodeList       - Array of graph store node objects
 * @param {object[]} connectionList - Array of graph store connection objects
 * @returns {{ version: string, nodes: object[], edges: object[] }}
 */
export function graphToKirgraph(nodeList, connectionList) {
  // Build a map from portId -> portName for all nodes so we can resolve
  // port names when converting connections.
  const portNameById = new Map() // portId -> portName

  const nodes = nodeList.map(node => {
    // Register all port ids -> names for edge conversion
    for (const p of node.dataPorts.inputs)   portNameById.set(p.id, p.name)
    for (const p of node.dataPorts.outputs)  portNameById.set(p.id, p.name)
    for (const p of node.controlPorts.inputs)  portNameById.set(p.id, p.name)
    for (const p of node.controlPorts.outputs) portNameById.set(p.id, p.name)

    // Convert data ports
    const data_inputs = node.dataPorts.inputs.map(p => {
      const obj = { port: p.name, type: p.dataType ?? 'any' }
      if (p.defaultValue !== undefined && p.defaultValue !== null) {
        obj.default = p.defaultValue
      }
      return obj
    })

    const data_outputs = node.dataPorts.outputs.map(p => ({
      port: p.name,
      type: p.dataType ?? 'any',
    }))

    // Control ports are just arrays of name strings per spec
    const ctrl_inputs  = node.controlPorts.inputs.map(p => p.name)
    const ctrl_outputs = node.controlPorts.outputs.map(p => p.name)

    // Position and size metadata
    const meta = {
      pos:  [Math.round(node.x), Math.round(node.y)],
      size: [Math.round(node.width), Math.round(node.height)],
    }

    const kgNode = {
      id:           node.id,
      type:         node.type,
      name:         node.name,
      data_inputs,
      data_outputs,
      ctrl_inputs,
      ctrl_outputs,
      meta,
    }

    // Only include properties if the node has any
    if (node.properties && Object.keys(node.properties).length > 0) {
      kgNode.properties = { ...node.properties }
    }

    return kgNode
  })

  const edges = connectionList.map(conn => {
    const fromPortName = portNameById.get(conn.fromPortId) ?? conn.fromPortId
    const toPortName   = portNameById.get(conn.toPortId)   ?? conn.toPortId

    return {
      type: conn.portType === 'control' ? 'control' : 'data',
      from: { node: conn.fromNodeId, port: fromPortName },
      to:   { node: conn.toNodeId,   port: toPortName   },
    }
  })

  return {
    version: '0.1.0',
    nodes,
    edges,
  }
}

// ---------------------------------------------------------------------------
// kirgraphToGraph
// ---------------------------------------------------------------------------

/**
 * Import a .kirgraph JSON object into graph store format.
 *
 * Returns plain objects that can be passed directly to graph.addNode() and
 * graph.addConnection(). Port ids are synthesised from node id + port name so
 * the edge lookup can work without a separate id registry.
 *
 * @param {{ version: string, nodes: object[], edges: object[] }} kirgraph
 * @returns {{ nodes: object[], connections: object[] }}
 */
export function kirgraphToGraph(kirgraph) {
  // We need to map (nodeId, portName, direction) → a stable portId so edges
  // can reference the same id that addNode() will store. We keep it simple:
  // portId = `${nodeId}__${portName}__${direction}` where direction is 'in'|'out'.
  // addNode() accepts port objects with explicit ids, so we just pass them through.

  function makePortId(nodeId, portName, suffix) {
    // Sanitise portName for use in an id (strip special chars)
    const safe = portName.replace(/[^a-zA-Z0-9_]/g, '_')
    return `${nodeId}__${safe}__${suffix}`
  }

  const nodes = (kirgraph.nodes ?? []).map(kgNode => {
    // Reconstruct dataPorts.inputs
    const dataInputs = (kgNode.data_inputs ?? []).map(p => {
      const port = {
        id:       makePortId(kgNode.id, p.port, 'di'),
        name:     p.port,
        dataType: p.type ?? 'any',
      }
      if (p.default !== undefined) port.defaultValue = p.default
      return port
    })

    // Reconstruct dataPorts.outputs
    const dataOutputs = (kgNode.data_outputs ?? []).map(p => ({
      id:       makePortId(kgNode.id, p.port, 'do'),
      name:     p.port,
      dataType: p.type ?? 'any',
    }))

    // Reconstruct controlPorts — ctrl_inputs/outputs are arrays of name strings
    const ctrlInputs = (kgNode.ctrl_inputs ?? []).map(name => ({
      id:   makePortId(kgNode.id, name, 'ci'),
      name,
    }))

    const ctrlOutputs = (kgNode.ctrl_outputs ?? []).map(name => ({
      id:   makePortId(kgNode.id, name, 'co'),
      name,
    }))

    // Position / size from meta
    const pos  = kgNode.meta?.pos  ?? [0, 0]
    const size = kgNode.meta?.size ?? [160, 120]

    return {
      id:   kgNode.id,
      type: kgNode.type ?? 'function',
      name: kgNode.name ?? kgNode.type ?? 'Node',
      x:    pos[0]  ?? 0,
      y:    pos[1]  ?? 0,
      width:  size[0] ?? 160,
      height: size[1] ?? 120,
      dataPorts: {
        inputs:  dataInputs,
        outputs: dataOutputs,
      },
      controlPorts: {
        inputs:  ctrlInputs,
        outputs: ctrlOutputs,
      },
      properties: kgNode.properties ?? {},
    }
  })

  // Build a lookup: (nodeId, portName) → portId, for each side/direction
  // We need to reverse-map from edge (nodeId, portName) → the portId we generated.
  const portIdLookup = new Map() // `${nodeId}|${portName}|${suffix}` -> portId

  for (const node of nodes) {
    for (const p of node.dataPorts.inputs)    portIdLookup.set(`${node.id}|${p.name}|di`, p.id)
    for (const p of node.dataPorts.outputs)   portIdLookup.set(`${node.id}|${p.name}|do`, p.id)
    for (const p of node.controlPorts.inputs)  portIdLookup.set(`${node.id}|${p.name}|ci`, p.id)
    for (const p of node.controlPorts.outputs) portIdLookup.set(`${node.id}|${p.name}|co`, p.id)
  }

  const connections = (kirgraph.edges ?? []).map((edge, i) => {
    const isCtrl = edge.type === 'control'

    // Determine the port id suffixes based on edge type and direction
    const fromSuffix = isCtrl ? 'co' : 'do'
    const toSuffix   = isCtrl ? 'ci' : 'di'

    const fromPortId = portIdLookup.get(`${edge.from.node}|${edge.from.port}|${fromSuffix}`)
      ?? makePortId(edge.from.node, edge.from.port, fromSuffix)
    const toPortId   = portIdLookup.get(`${edge.to.node}|${edge.to.port}|${toSuffix}`)
      ?? makePortId(edge.to.node, edge.to.port, toSuffix)

    return {
      // id is generated by graph.addConnection(); we carry a placeholder so
      // callers that iterate over the array can reference entries by index.
      _edgeIndex:  i,
      fromNodeId:  edge.from.node,
      fromPortId,
      toNodeId:    edge.to.node,
      toPortId,
      portType:    isCtrl ? 'control' : 'data',
    }
  })

  return { nodes, connections }
}
