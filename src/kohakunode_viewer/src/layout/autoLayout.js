/**
 * Auto-layout for viewer nodes — Fischer-style.
 *
 * Data dependencies flow LEFT → RIGHT (columns by data depth).
 * Control dependencies flow TOP → BOTTOM (order within columns).
 * Goal: minimize wire bending.
 */

const CTRL_ROW_H = 18;
const HEADER_H = 32;
const DATA_ROW_H = 28;
const H_GAP = 80;
const V_GAP = 50;

function estimateSize(node) {
  const nIn = (node.dataInputs || []).length;
  const nOut = (node.dataOutputs || []).length;
  const nCtrlIn = (node.ctrlInputs || []).length;
  const nCtrlOut = (node.ctrlOutputs || []).length;
  const dataRows = Math.max(nIn, nOut);
  const w = Math.max(180, Math.max(nCtrlIn, nCtrlOut) * 60 + 60);
  const h =
    (nCtrlIn > 0 ? CTRL_ROW_H : 0) +
    HEADER_H +
    dataRows * DATA_ROW_H +
    (nCtrlOut > 0 ? CTRL_ROW_H : 0) +
    16;
  return { w: Math.max(w, node.width || 0), h: Math.max(h, node.height || 0) };
}

export function autoLayout(nodes, edges) {
  if (!nodes || nodes.length === 0) return nodes;

  const dataAdj = {};
  const dataRev = {};
  const ctrlAdj = {};

  for (const e of edges) {
    if (e.type === "data") {
      if (!dataAdj[e.fromNode]) dataAdj[e.fromNode] = [];
      dataAdj[e.fromNode].push(e.toNode);
      if (!dataRev[e.toNode]) dataRev[e.toNode] = [];
      dataRev[e.toNode].push(e.fromNode);
    } else if (e.type === "control") {
      if (!ctrlAdj[e.fromNode]) ctrlAdj[e.fromNode] = [];
      ctrlAdj[e.fromNode].push(e.toNode);
    }
  }

  const nodeMap = {};
  const sizes = {};
  for (const n of nodes) {
    nodeMap[n.id] = n;
    sizes[n.id] = estimateSize(n);
  }

  const allIds = nodes.map((n) => n.id);
  const needsLayout = allIds.filter((id) => !nodeMap[id].x && !nodeMap[id].y);
  if (needsLayout.length === 0) {
    // Still update sizes
    for (const n of nodes) {
      const s = sizes[n.id];
      n.width = s.w;
      n.height = s.h;
    }
    return nodes;
  }

  // Column assignment: data dependency depth (BFS)
  const col = {};
  const roots = allIds.filter((id) => !dataRev[id] || dataRev[id].length === 0);
  if (roots.length === 0) roots.push(allIds[0]);

  const queue = [...roots];
  for (const r of roots) col[r] = 0;
  let qi = 0;
  while (qi < queue.length) {
    const nid = queue[qi++];
    for (const child of dataAdj[nid] || []) {
      const nc = (col[nid] || 0) + 1;
      if (col[child] === undefined || col[child] < nc) {
        col[child] = nc;
        queue.push(child);
      }
    }
  }
  const maxCol = Math.max(0, ...Object.values(col));
  for (const id of allIds) {
    if (col[id] === undefined) col[id] = maxCol + 1;
  }

  // Group by column
  const columns = {};
  for (const id of allIds) {
    const c = col[id];
    if (!columns[c]) columns[c] = [];
    columns[c].push(id);
  }

  // Order within columns by control flow
  for (const ids of Object.values(columns)) {
    const inCol = new Set(ids);
    const order = {};
    let idx = 0;
    const ctrlRoots = ids.filter(
      (id) =>
        !Object.entries(ctrlAdj).some(
          ([from, tos]) => tos.includes(id) && inCol.has(from)
        )
    );
    const bfs = ctrlRoots.length > 0 ? [...ctrlRoots] : [ids[0]];
    const vis = new Set();
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
    for (const id of ids) {
      if (!vis.has(id)) order[id] = idx++;
    }
    ids.sort((a, b) => (order[a] || 0) - (order[b] || 0));
  }

  // Assign coordinates
  const sortedCols = Object.keys(columns).map(Number).sort((a, b) => a - b);
  let xOff = 100;
  for (const c of sortedCols) {
    const ids = columns[c];
    const colW = Math.max(...ids.map((id) => sizes[id].w));
    let yOff = 100;
    for (const id of ids) {
      const s = sizes[id];
      const n = nodeMap[id];
      if (!n.x && !n.y) {
        n.x = xOff;
        n.y = yOff;
      }
      n.width = s.w;
      n.height = s.h;
      yOff += s.h + V_GAP;
    }
    xOff += colW + H_GAP;
  }

  return nodes;
}
