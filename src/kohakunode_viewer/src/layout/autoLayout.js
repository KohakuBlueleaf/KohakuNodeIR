/**
 * Auto-layout — matches auto_layout.py (Fischer-style).
 *
 * Column assignment: DATA edges only (left → right).
 * Value nodes placed adjacent to first consumer (col - 1).
 * Ctrl-connected nodes pulled to same column when safe.
 * Within each column, order by ctrl BFS (top → bottom).
 * Size estimation from port counts.
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
  const h = Math.max(
    MIN_HEIGHT,
    (nCtrlIn > 0 ? CTRL_ROW_H : 0) +
      HEADER_H +
      dataRows * DATA_ROW_H +
      (nCtrlOut > 0 ? CTRL_ROW_H : 0) +
      8
  );
  return { w, h };
}

export function autoLayout(nodes, edges) {
  if (!nodes || nodes.length === 0) return nodes;

  // Build layout-node metadata for all nodes
  const lnodes = {};
  for (const n of nodes) {
    const { w, h } = estimateSize(n);
    // Respect existing size from @meta if larger
    let fw = w;
    let fh = h;
    if (n.width && n.height) {
      fw = Math.max(fw, n.width);
      fh = Math.max(fh, n.height);
    }
    const hasPos = !!(n.x || n.y);
    lnodes[n.id] = {
      id: n.id,
      width: fw,
      height: fh,
      x: n.x || 0,
      y: n.y || 0,
      hasPosition: hasPos,
      dataInCount: (n.dataInputs || []).length,
      dataOutCount: (n.dataOutputs || []).length,
      ctrlInCount: (n.ctrlInputs || []).length,
      ctrlOutCount: (n.ctrlOutputs || []).length,
    };
  }

  // Collect nodes that need layout
  const needsIds = Object.keys(lnodes).filter((id) => !lnodes[id].hasPosition);
  if (needsIds.length === 0) return nodes;
  const needsSet = new Set(needsIds);

  // Build separate data and ctrl adjacency
  const dataAdj = {}; // from → [to]  (data edges only)
  const dataRev = {}; // to → [from]  (data edges only)
  const ctrlAdj = {}; // from → [to]  (ctrl edges only)
  const ctrlRev = {}; // to → [from]  (ctrl edges only)

  for (const e of edges) {
    const f = e.fromNode;
    const t = e.toNode;
    if (e.type === "data") {
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

  // ── Step 1: Column assignment using DATA edges only (BFS longest path) ──
  const col = {};
  const dataRoots = needsIds.filter((id) => !(dataRev[id] && dataRev[id].length > 0));
  const startRoots = dataRoots.length > 0 ? dataRoots : [needsIds[0]];

  const queue = [...startRoots];
  for (const r of startRoots) col[r] = 0;
  let qi = 0;
  while (qi < queue.length) {
    const nid = queue[qi++];
    for (const child of dataAdj[nid] || []) {
      if (!needsSet.has(child)) continue;
      const nc = (col[nid] || 0) + 1;
      if (col[child] === undefined || col[child] < nc) {
        col[child] = nc;
        queue.push(child);
      }
    }
  }
  // Unassigned nodes
  const maxColSoFar = needsIds.reduce((m, id) => Math.max(m, col[id] ?? -1), 0);
  for (const id of needsIds) {
    if (col[id] === undefined) col[id] = maxColSoFar + 1;
  }

  // ── Step 2: Value nodes → place one column before first consumer ──
  // A value/source node: no data inputs, has data outputs, no ctrl inputs
  for (const id of needsIds) {
    const ln = lnodes[id];
    if (ln.dataInCount === 0 && ln.dataOutCount > 0 && ln.ctrlInCount === 0) {
      const consumers = (dataAdj[id] || []).filter((c) => c in col);
      if (consumers.length > 0) {
        const consumerCol = Math.min(...consumers.map((c) => col[c]));
        col[id] = Math.max(0, consumerCol - 1);
      }
    }
  }

  // ── Step 3: Ctrl-connected nodes → pull to same column ──
  // If A→B via ctrl and child has no data-based reason to be elsewhere, move B to A's col.
  for (const nid of needsIds) {
    for (const child of ctrlAdj[nid] || []) {
      if (!needsSet.has(child)) continue;
      if (col[child] === col[nid]) continue;
      // Only move if child's column assignment did not come from data edges to it
      const childDataSources = dataRev[child] || [];
      const hasDataReason = childDataSources.some((s) => needsSet.has(s));
      if (!hasDataReason) {
        col[child] = col[nid];
      }
    }
  }

  // ── Step 4: Group by column; order within column by ctrl BFS ──
  const columns = {};
  for (const id of needsIds) {
    const c = col[id];
    if (!columns[c]) columns[c] = [];
    columns[c].push(id);
  }

  for (const ids of Object.values(columns)) {
    const inCol = new Set(ids);
    const order = {};
    let idx = 0;

    // Ctrl roots: no ctrl predecessor inside this column
    const cRoots = ids.filter(
      (id) => !(ctrlRev[id] || []).some((src) => inCol.has(src))
    );
    const bfsStart = cRoots.length > 0 ? cRoots : [ids[0]];

    const vis = new Set();
    const bfs = [...bfsStart];
    for (const r of bfs) {
      if (!vis.has(r)) { vis.add(r); order[r] = idx++; }
    }
    let bi = 0;
    while (bi < bfs.length) {
      for (const child of ctrlAdj[bfs[bi]] || []) {
        if (inCol.has(child) && !vis.has(child)) {
          vis.add(child);
          order[child] = idx++;
          bfs.push(child);
        }
      }
      bi++;
    }
    // Remaining unvisited (data-only deps, disconnected within col)
    for (const id of ids) {
      if (!vis.has(id)) order[id] = idx++;
    }

    ids.sort((a, b) => (order[a] ?? 999) - (order[b] ?? 999));
  }

  // ── Step 5: Assign coordinates ──
  const sortedCols = Object.keys(columns).map(Number).sort((a, b) => a - b);
  let xOff = 100;
  for (const c of sortedCols) {
    const ids = columns[c];
    const colW = Math.max(...ids.map((id) => lnodes[id].width));
    let yOff = 100;
    for (const id of ids) {
      lnodes[id].x = xOff;
      lnodes[id].y = yOff;
      yOff += lnodes[id].height + V_SPACING;
    }
    xOff += colW + H_SPACING;
  }

  // ── Step 6: Write positions back to node objects ──
  const nodeMap = {};
  for (const n of nodes) nodeMap[n.id] = n;

  for (const id of needsIds) {
    const ln = lnodes[id];
    const n = nodeMap[id];
    if (n) {
      n.x = ln.x;
      n.y = ln.y;
      n.width = ln.width;
      n.height = ln.height;
    }
  }

  // Also update sizes for nodes that already had positions (size recalc)
  for (const n of nodes) {
    if (lnodes[n.id] && lnodes[n.id].hasPosition) {
      n.width = lnodes[n.id].width;
      n.height = lnodes[n.id].height;
    }
  }

  return nodes;
}
