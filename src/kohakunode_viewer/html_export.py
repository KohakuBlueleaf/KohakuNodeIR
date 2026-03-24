"""Self-contained HTML export for KirGraph visualisation.

Generates a single HTML file (no external dependencies) that renders
the graph as positioned nodes with SVG edges, supports pan/zoom via
mouse drag and wheel, and embeds the kirgraph JSON inline.
"""

from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Colour palette (Catppuccin Mocha-inspired, matches the Vue viewer)
# ---------------------------------------------------------------------------

_BG = "#11111b"
_NODE_BG = "#1e1e2e"
_NODE_BORDER = "#313244"
_NODE_HEADER = "#181825"
_TEXT = "#cdd6f4"
_TEXT_DIM = "#6c7086"
_CTRL_EDGE = "#89dceb"
_DATA_EDGE = "#a6e3a1"
_PORT_CTRL = "#89dceb"
_PORT_DATA = "#a6e3a1"

# Node header colours by type
_TYPE_COLOURS: dict[str, str] = {
    "value": "#fab387",
    "branch": "#f38ba8",
    "merge": "#cba6f7",
    "switch": "#f9e2af",
    "parallel": "#89dceb",
    "function": "#89b4fa",
}
_DEFAULT_HEADER = "#89b4fa"

_NODE_W = 180
_NODE_HEADER_H = 28
_PORT_H = 22
_PORT_R = 5

# ---------------------------------------------------------------------------
# HTML/CSS/JS template
# The placeholders __GRAPH_JSON__, __TYPE_CLR__, __CONSTANTS__ are replaced
# at generation time; no f-string is used for the JS block to avoid brace
# escaping issues.
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>KirGraph Viewer</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%;overflow:hidden;background:__BG__;color:__TEXT__;font-family:monospace,ui-monospace,sans-serif;font-size:12px}
#app{width:100%;height:100%;position:relative;overflow:hidden;cursor:grab}
#app.dragging{cursor:grabbing}
#canvas{position:absolute;top:0;left:0;transform-origin:0 0;will-change:transform}
.node{position:absolute;background:__NODE_BG__;border:1px solid __NODE_BORDER__;border-radius:6px;min-width:__NODE_W__px;box-shadow:0 4px 16px rgba(0,0,0,.5)}
.node-header{border-radius:5px 5px 0 0;padding:0 8px;height:__HDR_H__px;display:flex;align-items:center;font-weight:600;font-size:11px;letter-spacing:.04em;background:var(--hdr)}
.node-body{padding:6px 0}
.port-row{display:flex;align-items:center;height:__PORT_H__px;position:relative}
.port-row.left{justify-content:flex-start;padding-left:4px}
.port-row.right{justify-content:flex-end;padding-right:4px}
.port-dot{width:__PORT_D__px;height:__PORT_D__px;border-radius:50%;flex-shrink:0;border:1px solid rgba(255,255,255,.25)}
.port-label{font-size:10px;color:__TEXT_DIM__;padding:0 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px}
svg#edges{position:absolute;top:0;left:0;pointer-events:none;overflow:visible}
.edge-ctrl{stroke:__CTRL_EDGE__;fill:none;stroke-width:1.8;opacity:.85}
.edge-data{stroke:__DATA_EDGE__;fill:none;stroke-width:1.5;opacity:.75}
#hud{position:fixed;bottom:12px;right:14px;color:__TEXT_DIM__;font-size:10px;pointer-events:none;user-select:none}
#hud kbd{background:#313244;border-radius:3px;padding:1px 4px;color:__TEXT__}
</style>
</head>
<body>
<div id="app">
  <svg id="edges"></svg>
  <div id="canvas"></div>
</div>
<div id="hud"><kbd>drag</kbd> pan &nbsp; <kbd>wheel</kbd> zoom &nbsp; <kbd>scroll</kbd> pan</div>
<script>
(function(){
"use strict";

// embedded graph data
const GRAPH = __GRAPH_JSON__;

// constants
const NODE_W   = __NODE_W__;
const PORT_H   = __PORT_H__;
const PORT_R   = __PORT_R__;
const HDR_H    = __HDR_H__;
const TYPE_CLR = __TYPE_CLR__;
const DEFAULT_HDR = "__DEFAULT_HDR__";
const PORT_CTRL   = "__PORT_CTRL__";
const PORT_DATA   = "__PORT_DATA__";

// helpers
function hdrClr(t){ return TYPE_CLR[t] || DEFAULT_HDR; }

function portClr(kind){
  return kind === "ctrl" ? PORT_CTRL : PORT_DATA;
}

function nodeHeight(n){
  const l = (n.data_inputs||[]).length + (n.ctrl_inputs||[]).length;
  const r = (n.data_outputs||[]).length + (n.ctrl_outputs||[]).length;
  return HDR_H + Math.max(l, r, 1) * PORT_H + 12;
}

// state
let tx=0, ty=0, scale=1;
let dragging=false, lastX=0, lastY=0;

// node map
const nodeMap = {};
(GRAPH.nodes||[]).forEach(n => { nodeMap[n.id] = n; });

// port centres in canvas-space
const portCentres = {};

function buildPortCentres(){
  (GRAPH.nodes||[]).forEach(n => {
    const meta = n.meta || {};
    const pos  = meta.pos  || [0, 0];
    const px = pos[0], py = pos[1];

    const leftPorts = [
      ...(n.ctrl_inputs||[]).map(p  => ({ name: p,      kind: "ctrl" })),
      ...(n.data_inputs||[]).map(p  => ({ name: p.port, kind: "data" })),
    ];
    const rightPorts = [
      ...(n.ctrl_outputs||[]).map(p => ({ name: p,      kind: "ctrl" })),
      ...(n.data_outputs||[]).map(p => ({ name: p.port, kind: "data" })),
    ];

    leftPorts.forEach((p, i) => {
      portCentres[n.id + ":in:"  + p.name] = {
        x: px,
        y: py + HDR_H + 6 + i * PORT_H + PORT_H / 2,
        kind: p.kind,
      };
    });
    rightPorts.forEach((p, i) => {
      portCentres[n.id + ":out:" + p.name] = {
        x: px + NODE_W,
        y: py + HDR_H + 6 + i * PORT_H + PORT_H / 2,
        kind: p.kind,
      };
    });
  });
}

// DOM helpers
function el(tag, cls, txt){
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt !== undefined) e.textContent = txt;
  return e;
}

function portRow(name, kind, side){
  const row  = el("div", "port-row " + side);
  const dot  = el("div", "port-dot");
  dot.style.background = portClr(kind);
  const lbl  = el("span", "port-label", name);
  if (side === "left") { row.appendChild(dot); row.appendChild(lbl); }
  else                 { row.appendChild(lbl); row.appendChild(dot); }
  return row;
}

// render nodes
function renderNodes(){
  const canvas = document.getElementById("canvas");
  canvas.innerHTML = "";
  (GRAPH.nodes||[]).forEach(n => {
    const meta = n.meta || {};
    const pos  = meta.pos || [0, 0];
    const div  = el("div", "node");
    div.style.left = pos[0] + "px";
    div.style.top  = pos[1] + "px";
    div.style.setProperty("--hdr", hdrClr(n.type));

    div.appendChild(el("div", "node-header", n.name || n.id));

    const body = el("div", "node-body");
    const leftPorts = [
      ...(n.ctrl_inputs||[]).map(p  => ({ name: p,      kind: "ctrl" })),
      ...(n.data_inputs||[]).map(p  => ({ name: p.port, kind: "data" })),
    ];
    const rightPorts = [
      ...(n.ctrl_outputs||[]).map(p => ({ name: p,      kind: "ctrl" })),
      ...(n.data_outputs||[]).map(p => ({ name: p.port, kind: "data" })),
    ];
    const rows = Math.max(leftPorts.length, rightPorts.length, 1);

    for (let i = 0; i < rows; i++){
      const rowWrap = el("div");
      rowWrap.style.cssText = "display:flex;justify-content:space-between;height:" + PORT_H + "px;";
      rowWrap.appendChild(
        i < leftPorts.length  ? portRow(leftPorts[i].name,  leftPorts[i].kind,  "left")
                               : el("div", "port-row left")
      );
      rowWrap.appendChild(
        i < rightPorts.length ? portRow(rightPorts[i].name, rightPorts[i].kind, "right")
                               : el("div", "port-row right")
      );
      body.appendChild(rowWrap);
    }
    div.appendChild(body);
    canvas.appendChild(div);
  });
}

// render edges (bezier curves)
function cubicPath(x1, y1, x2, y2){
  const dx = Math.abs(x2 - x1) * 0.5 + 40;
  return "M" + x1 + "," + y1
       + " C" + (x1+dx) + "," + y1
       + " " + (x2-dx) + "," + y2
       + " " + x2 + "," + y2;
}

function renderEdges(){
  const svg = document.getElementById("edges");
  svg.innerHTML = "";
  (GRAPH.edges||[]).forEach(e => {
    const fp = portCentres[e.from.node + ":out:" + e.from.port];
    const tp = portCentres[e.to.node   + ":in:"  + e.to.port];
    if (!fp || !tp) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", cubicPath(fp.x, fp.y, tp.x, tp.y));
    path.setAttribute("class", e.type === "control" ? "edge-ctrl" : "edge-data");
    svg.appendChild(path);
  });
}

// pan / zoom
function applyTransform(){
  const t = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
  document.getElementById("canvas").style.transform = t;
  document.getElementById("edges").style.transform  = t;
}

const app = document.getElementById("app");

app.addEventListener("mousedown", e => {
  if (e.button !== 0) return;
  dragging = true; lastX = e.clientX; lastY = e.clientY;
  app.classList.add("dragging");
});
window.addEventListener("mousemove", e => {
  if (!dragging) return;
  tx += e.clientX - lastX; ty += e.clientY - lastY;
  lastX = e.clientX; lastY = e.clientY;
  applyTransform();
});
window.addEventListener("mouseup", () => {
  dragging = false;
  app.classList.remove("dragging");
});

app.addEventListener("wheel", e => {
  e.preventDefault();
  if (e.ctrlKey || e.metaKey){
    const rect   = app.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.1 : 1/1.1;
    tx = (tx - cx) * factor + cx;
    ty = (ty - cy) * factor + cy;
    scale = Math.max(0.1, Math.min(4, scale * factor));
  } else {
    tx -= e.deltaX; ty -= e.deltaY;
  }
  applyTransform();
}, { passive: false });

// touch pan/zoom
let lastTouches = null;
app.addEventListener("touchstart",  e => { lastTouches = e.touches; }, { passive: true });
app.addEventListener("touchmove", e => {
  e.preventDefault();
  if (e.touches.length === 1 && lastTouches && lastTouches.length === 1){
    tx += e.touches[0].clientX - lastTouches[0].clientX;
    ty += e.touches[0].clientY - lastTouches[0].clientY;
  } else if (e.touches.length === 2 && lastTouches && lastTouches.length === 2){
    const prevD = Math.hypot(
      lastTouches[0].clientX - lastTouches[1].clientX,
      lastTouches[0].clientY - lastTouches[1].clientY
    );
    const currD = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    const factor = currD / prevD;
    const cx = (e.touches[0].clientX + e.touches[1].clientX) / 2;
    const cy = (e.touches[0].clientY + e.touches[1].clientY) / 2;
    tx = (tx - cx) * factor + cx;
    ty = (ty - cy) * factor + cy;
    scale = Math.max(0.1, Math.min(4, scale * factor));
  }
  lastTouches = e.touches;
  applyTransform();
}, { passive: false });

// fit graph to viewport on load
function fitGraph(){
  if (!(GRAPH.nodes && GRAPH.nodes.length)) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  (GRAPH.nodes||[]).forEach(n => {
    const pos = (n.meta || {}).pos || [0, 0];
    minX = Math.min(minX, pos[0]);
    minY = Math.min(minY, pos[1]);
    maxX = Math.max(maxX, pos[0] + NODE_W);
    maxY = Math.max(maxY, pos[1] + nodeHeight(n));
  });
  const gw = maxX - minX + 80;
  const gh = maxY - minY + 80;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  scale = Math.min(vw / gw, vh / gh, 1.5);
  tx = (vw - gw * scale) / 2 - minX * scale + 40 * scale;
  ty = (vh - gh * scale) / 2 - minY * scale + 40 * scale;
  applyTransform();
}

// init
renderNodes();
buildPortCentres();
renderEdges();
fitGraph();

})();
</script>
</body>
</html>
"""


def generate_html(kirgraph_json: str) -> str:
    """Generate a self-contained HTML file that visualises the graph.

    Args:
        kirgraph_json: The serialised KirGraph JSON string.

    Returns:
        A complete HTML document as a string.
    """
    # Validate JSON is parseable — raises ValueError on bad input.
    graph = json.loads(kirgraph_json)
    # Re-serialise compactly for embedding.
    embedded = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    type_clr = json.dumps(_TYPE_COLOURS, ensure_ascii=False)

    html = _HTML_TEMPLATE
    html = html.replace("__GRAPH_JSON__", embedded)
    html = html.replace("__TYPE_CLR__", type_clr)

    # Scalar constants (CSS and JS)
    html = html.replace("__BG__", _BG)
    html = html.replace("__TEXT_DIM__", _TEXT_DIM)
    html = html.replace("__TEXT__", _TEXT)
    html = html.replace("__NODE_BG__", _NODE_BG)
    html = html.replace("__NODE_BORDER__", _NODE_BORDER)
    html = html.replace("__CTRL_EDGE__", _CTRL_EDGE)
    html = html.replace("__DATA_EDGE__", _DATA_EDGE)
    html = html.replace("__PORT_CTRL__", _PORT_CTRL)
    html = html.replace("__PORT_DATA__", _PORT_DATA)
    html = html.replace("__DEFAULT_HDR__", _DEFAULT_HEADER)
    html = html.replace("__NODE_W__", str(_NODE_W))
    html = html.replace("__PORT_H__", str(_PORT_H))
    html = html.replace("__PORT_R__", str(_PORT_R))
    html = html.replace("__PORT_D__", str(_PORT_R * 2))
    html = html.replace("__HDR_H__", str(_NODE_HEADER_H))

    return html
