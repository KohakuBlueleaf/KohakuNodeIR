/**
 * Auto-layout — matches auto_layout.py.
 *
 * 1. Ctrl root at grid (0, 0), ctrl chain goes DOWN
 * 2. Data sources placed LEFT of consumers
 * 3. Data consumers placed RIGHT of sources
 * 4. Negative grid indices allowed, shifted at the end
 */

const CTRL_ROW_H = 18;
const HEADER_H = 32;
const DATA_ROW_H = 28;
const MIN_WIDTH = 180;
const MIN_HEIGHT = 100;
const H_SPACING = 60;
const V_SPACING = 40;

function estimateSize(node) {
  const nIn = (node.dataInputs || []).length;
  const nOut = (node.dataOutputs || []).length;
  const nCtrlIn = (node.ctrlInputs || []).length;
  const nCtrlOut = (node.ctrlOutputs || []).length;
  const dataRows = Math.max(nIn, nOut);
  const w = Math.max(MIN_WIDTH, Math.max(nCtrlIn, nCtrlOut) * 60 + 60);
  let h;
  if (node.type === 'merge') {
    h = (nCtrlIn > 0 ? CTRL_ROW_H : 0) + HEADER_H + (nCtrlOut > 0 ? CTRL_ROW_H : 0) + 8;
  } else {
    h = Math.max(
      MIN_HEIGHT,
      (nCtrlIn > 0 ? CTRL_ROW_H : 0) +
        HEADER_H +
        dataRows * DATA_ROW_H +
        (nCtrlOut > 0 ? CTRL_ROW_H : 0) +
        8
    );
  }
  return { w, h };
}

export function autoLayout(nodes, edges) {
  if (!nodes || nodes.length === 0) return nodes;

  // Size estimation for all nodes
  const sizes = {};
  for (const n of nodes) {
    sizes[n.id] = estimateSize(n);
    n.width = sizes[n.id].w;
    n.height = sizes[n.id].h;
  }

  const needsIds = nodes.filter((n) => !n.x && !n.y).map((n) => n.id);
  if (needsIds.length === 0) return nodes;
  const needsSet = new Set(needsIds);

  // Build adjacency
  const dataAdj = {},
    dataRev = {},
    ctrlAdj = {},
    ctrlRev = {};
  for (const e of edges) {
    const f = e.fromNode,
      t = e.toNode;
    if (e.type === 'data') {
      if (!dataAdj[f]) dataAdj[f] = [];
      dataAdj[f].push(t);
      if (!dataRev[t]) dataRev[t] = [];
      dataRev[t].push(f);
    } else {
      if (!ctrlAdj[f]) ctrlAdj[f] = [];
      ctrlAdj[f].push(t);
      if (!ctrlRev[t]) ctrlRev[t] = [];
      ctrlRev[t].push(f);
    }
  }

  // Node order for back-edge detection (preserve graph order)
  const nodeRank = {};
  needsIds.forEach((id, i) => {
    nodeRank[id] = i;
  });

  // Build node type map for merge rank fixup
  const nodeTypeMap = {};
  for (const n of nodes) nodeTypeMap[n.id] = n.type;

  const grid = {}; // id → [col, row]
  const placed = new Set();
  const gridCells = new Set(); // "col,row" strings for collision check

  function isOccupied(c, r) {
    return gridCells.has(`${c},${r}`);
  }
  function place(id, c, r) {
    grid[id] = [c, r];
    placed.add(id);
    gridCells.add(`${c},${r}`);
  }

  // ── Step 1: Ctrl root at (0,0), ctrl chain downward ──
  // Collect all nodes in ctrl edges
  const ctrlNodes = new Set();
  for (const e of edges) {
    if (e.type !== 'data') {
      if (needsSet.has(e.fromNode)) ctrlNodes.add(e.fromNode);
      if (needsSet.has(e.toNode)) ctrlNodes.add(e.toNode);
    }
  }

  // Find root: has ctrl outputs, no forward incoming ctrl
  let ctrlRoots = needsIds.filter((id) => {
    if (!ctrlNodes.has(id)) return false;
    if (!(ctrlAdj[id] || []).length) return false;
    const incoming = (ctrlRev[id] || []).filter((s) => needsSet.has(s));
    const forwardIncoming = incoming.filter((s) => (nodeRank[s] ?? 999) < (nodeRank[id] ?? 0));
    return forwardIncoming.length === 0;
  });

  if (ctrlRoots.length === 0 && ctrlNodes.size > 0) {
    // All ctrl nodes in a cycle — pick first in graph order
    for (const id of needsIds) {
      if (ctrlNodes.has(id)) {
        ctrlRoots = [id];
        break;
      }
    }
  }

  if (ctrlRoots.length === 0) {
    // No ctrl chain — find any root
    const allTo = new Set();
    for (const e of edges) allTo.add(e.toNode);
    ctrlRoots = needsIds.filter((id) => !allTo.has(id));
  }
  if (ctrlRoots.length === 0) ctrlRoots = [needsIds[0]];

  // Fix ranks for merge nodes: place just before their successor
  for (const id of needsIds) {
    if (nodeTypeMap[id] === 'merge') {
      for (const child of ctrlAdj[id] || []) {
        if (nodeRank[child] !== undefined) {
          nodeRank[id] = nodeRank[child] - 0.5;
          break;
        }
      }
    }
  }

  let ctrlRow = 0;

  function bfsCtrl(start) {
    if (placed.has(start)) return;
    place(start, 0, ctrlRow++);
    const q = [start];
    let qi = 0;
    while (qi < q.length) {
      const nid = q[qi++];
      for (const child of ctrlAdj[nid] || []) {
        if (needsSet.has(child) && !placed.has(child)) {
          if ((nodeRank[child] ?? 999) < (nodeRank[nid] ?? 0)) continue;
          place(child, 0, ctrlRow++);
          q.push(child);
        }
      }
    }
  }

  // Start from first ctrl root
  if (ctrlRoots.length > 0) bfsCtrl(ctrlRoots[0]);

  // Place remaining ctrl nodes not reached by initial BFS
  for (const id of needsIds) {
    if (ctrlNodes.has(id) && !placed.has(id)) {
      bfsCtrl(id);
    }
  }

  // ── Step 2: Data sources LEFT of consumers ──
  let changed = true;
  while (changed) {
    changed = false;
    for (const nid of needsIds) {
      if (placed.has(nid)) continue;
      const consumers = (dataAdj[nid] || []).filter((c) => placed.has(c));
      if (consumers.length > 0) {
        const positions = consumers.map((c) => grid[c]);
        const minCol = Math.min(...positions.map((p) => p[0]));
        const targetRow = positions[0][1];
        let col = minCol - 1;
        while (isOccupied(col, targetRow)) col--;
        place(nid, col, targetRow);
        changed = true;
      }
    }
  }

  // ── Step 3: Data consumers RIGHT of sources ──
  changed = true;
  while (changed) {
    changed = false;
    for (const nid of needsIds) {
      if (placed.has(nid)) continue;
      const sources = (dataRev[nid] || []).filter((s) => placed.has(s));
      if (sources.length > 0) {
        const positions = sources.map((s) => grid[s]);
        const maxCol = Math.max(...positions.map((p) => p[0]));
        const targetRow = positions[0][1];
        let col = maxCol + 1;
        while (isOccupied(col, targetRow)) col++;
        place(nid, col, targetRow);
        changed = true;
      }
    }
  }

  // ── Step 4: Remaining unconnected ──
  const maxRow = Math.max(0, ...Object.values(grid).map((p) => p[1])) + 1;
  let ri = 0;
  for (const nid of needsIds) {
    if (!placed.has(nid)) {
      place(nid, ri++, maxRow);
    }
  }

  // ── Step 5: Shift to positive + pixel coordinates ──
  const minCol = Math.min(...Object.values(grid).map((p) => p[0]));
  const minRow = Math.min(...Object.values(grid).map((p) => p[1]));

  // Column widths for pixel x
  const shifted = {};
  for (const [id, [c, r]] of Object.entries(grid)) {
    shifted[id] = [c - minCol, r - minRow];
  }

  const maxColVal = Math.max(0, ...Object.values(shifted).map((p) => p[0]));
  const colWidths = {};
  for (const [id, [c]] of Object.entries(shifted)) {
    colWidths[c] = Math.max(colWidths[c] || MIN_WIDTH, sizes[id].w);
  }

  const colX = {};
  let x = 100;
  for (let c = 0; c <= maxColVal; c++) {
    colX[c] = x;
    x += (colWidths[c] || MIN_WIDTH) + H_SPACING;
  }

  // Write back
  const nodeMap = {};
  for (const n of nodes) nodeMap[n.id] = n;

  for (const [id, [c, r]] of Object.entries(shifted)) {
    const n = nodeMap[id];
    if (n && needsSet.has(id)) {
      n.x = colX[c] || 100;
      n.y = 100 + r * (MIN_HEIGHT + V_SPACING);
      n.width = sizes[id].w;
      n.height = sizes[id].h;
    }
  }

  return nodes;
}
