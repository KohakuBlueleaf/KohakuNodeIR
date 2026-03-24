/**
 * Auto-layout — Fischer-style.
 *
 * Uses ALL edges (data + control) to determine column depth.
 * Data flows LEFT → RIGHT, control flows TOP → BOTTOM within columns.
 */

const CTRL_ROW_H = 18;
const HEADER_H = 32;
const DATA_ROW_H = 28;
const H_GAP = 80;
const V_GAP = 40;

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
    8;
  return { w, h };
}

export function autoLayout(nodes, edges) {
  if (!nodes || nodes.length === 0) return nodes;

  // Update sizes for ALL nodes
  const sizes = {};
  for (const n of nodes) {
    sizes[n.id] = estimateSize(n);
    n.width = sizes[n.id].w;
    n.height = sizes[n.id].h;
  }

  const needsLayout = nodes.filter((n) => !n.x && !n.y);
  if (needsLayout.length === 0) return nodes;

  // Build adjacency from ALL edges for column assignment
  const allAdj = {}; // from → [to]
  const allRev = {}; // to → [from]
  const ctrlAdj = {}; // for vertical ordering

  for (const e of edges) {
    const f = e.fromNode;
    const t = e.toNode;
    if (!allAdj[f]) allAdj[f] = [];
    allAdj[f].push(t);
    if (!allRev[t]) allRev[t] = [];
    allRev[t].push(f);
    if (e.type === "control") {
      if (!ctrlAdj[f]) ctrlAdj[f] = [];
      ctrlAdj[f].push(t);
    }
  }

  const nodeMap = {};
  for (const n of nodes) nodeMap[n.id] = n;
  const allIds = nodes.map((n) => n.id);

  // ── Column assignment: longest path from roots using ALL edges ──
  const col = {};
  const roots = allIds.filter((id) => !allRev[id] || allRev[id].length === 0);
  if (roots.length === 0) roots.push(allIds[0]);

  // Longest-path BFS (ensures dependent nodes are always in later columns)
  const queue = [...roots];
  for (const r of roots) col[r] = 0;
  let qi = 0;
  while (qi < queue.length) {
    const nid = queue[qi++];
    for (const child of allAdj[nid] || []) {
      const nc = (col[nid] || 0) + 1;
      if (col[child] === undefined || col[child] < nc) {
        col[child] = nc;
        queue.push(child);
      }
    }
  }
  // Disconnected nodes
  const maxCol = Math.max(0, ...Object.values(col));
  for (const id of allIds) {
    if (col[id] === undefined) col[id] = maxCol + 1;
  }

  // ── Group by column ──
  const columns = {};
  for (const id of allIds) {
    const c = col[id];
    if (!columns[c]) columns[c] = [];
    columns[c].push(id);
  }

  // ── Order within columns by control flow (top→bottom) ──
  for (const ids of Object.values(columns)) {
    const inCol = new Set(ids);
    const order = {};
    let idx = 0;

    // Find ctrl roots within this column
    const ctrlRoots = ids.filter((id) => {
      // No ctrl predecessor in this column
      for (const [from, tos] of Object.entries(ctrlAdj)) {
        if (tos.includes(id) && inCol.has(from)) return false;
      }
      return true;
    });

    // BFS within column following ctrl edges
    const vis = new Set();
    const bfs = ctrlRoots.length > 0 ? [...ctrlRoots] : [ids[0]];
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

  // ── Assign coordinates ──
  const sortedCols = Object.keys(columns).map(Number).sort((a, b) => a - b);
  let xOff = 100;
  for (const c of sortedCols) {
    const ids = columns[c];
    const colW = Math.max(...ids.map((id) => sizes[id].w));
    let yOff = 100;
    for (const id of ids) {
      const n = nodeMap[id];
      if (!n.x && !n.y) {
        n.x = xOff;
        n.y = yOff;
      }
      yOff += sizes[id].h + V_GAP;
    }
    xOff += colW + H_GAP;
  }

  return nodes;
}
