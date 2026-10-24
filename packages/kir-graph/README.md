# @kohaku/kir-graph

Display library for KIR programs. It draws a `.kirgraph` document (version 3,
from `kohakunode.graph.to_graph`) as a Vue component, in one of six views, with
a live overlay of run data (status, badges, heat) that never re-lays the graph
out. The graph views also edit (`editable`): the library reports every edit
as an event and never changes the document itself.

| view | draws | KIR data style |
|---|---|---|
| `flowchart` | flowchart elements (terminals, diamonds, merges), control wires, values through variable pills, graph inputs and outputs wired straight to their statements | `variables` |
| `nodes` | node cards with control and data wires | `wires` |
| `frames` | node cards boxed by region, control as order | `wires` |
| `dataflow` | data only, left to right | `wires` |
| `blocks` | Scratch-like blocks of statements (display only) | `variables` |
| `sequence` | EV3-like sequence of statements (display only) | `variables` |

`viewData(view)` names the data style a view is made for; draw the
`to_graph(program, env, viewData(view))` document in it.

## Install

The package ships a built ES module (`dist/`) and its source (`src/`). Vue, Vue
Flow and ELK are peer dependencies:

```sh
npm install vue @vue-flow/core @vue-flow/background @vue-flow/controls @vue-flow/minimap elkjs
```

then the library itself, from a release tarball:

```sh
npm install https://github.com/KohakuBlueleaf/KohakuNodeIR/releases/download/kir-graph-v0.1.0/kohaku-kir-graph-0.1.0.tgz
```

or from a checkout (build it once: `npm ci && npm run build` in this folder):

```sh
npm install ../KohakuNodeIR/packages/kir-graph
```

## Use

```vue
<script setup>
import { KirGraph, configureElk } from "@kohaku/kir-graph"
import "@kohaku/kir-graph/style.css"
import elkWorker from "elkjs/lib/elk-worker.min.js?url"

// Lay out off the main thread (Vite's ?url import); without it ELK runs inline
configureElk({ workerUrl: elkWorker })
defineProps({ doc: Object, overlay: Map })
</script>

<template>
  <KirGraph :doc="doc" graph="main" view="flowchart" :overlay="overlay" theme="dark" />
</template>
```

Props: `doc`, `graph`, `view`, `regions`, `collapsed` (v-model), `overlay` /
`edgeOverlay` / `regionOverlay` (Map or object keyed by node path or id),
`selected`, `theme` (`inherit`, `light`, `dark`), `wireStyle` (`rail`,
`plain`), `minimap`, `revision` (changes when `doc` was changed in place),
the editing props below, and `layout`, the layout knobs:

| knob | default | meaning |
|---|---|---|
| `compact` | on up to 400 elements | slide elements up and left after ELK, straighten the control trunk, route loop-back wires in the nearest clear lane |
| `wrap` | on | cut a tall drawing into macro columns |
| `aspect` | `1.4` | the width / height the macro columns aim for |
| `markRows` | `2` with an overlay, else `0` | rows of overlay marks kept clear above every element |
| `layering`, `placement` | ELK's network simplex | ELK `layering.strategy` and `nodePlacement.strategy` |

Events: `select`, `hover`, `layout` (`{ms, cached, nodes, regions, edges,
layout}`), `update:collapsed`. The model, geometry and layout functions
(`graphModel`, `layoutView`, `checkLayout`, ...) are exported for tools that
lay graphs out without the component. The default slot is drawn over the
view inside its theme; `.kg-theme` on any host element gives it the theme's
colour variables (for `typeColor` outside a graph).

### Editing

```vue
<KirGraph :doc="doc" :revision="version" :relayout-key="epoch" view="nodes" editable
          :is-valid-connection="vet" :drop-types="['application/x-my-node']"
          @connect="wire" @delete="remove" @drop="add" @edit="setLiteral" @move="moved" />
```

| event | payload | when |
|---|---|---|
| `connect` | `{source, sourceHandle, target, targetHandle}` (handles `flow:dir:port`) | a wire was drawn between two statements' pins that `isValidConnection(c)` accepts |
| `delete` | `{nodes: [id], edges: [edge key]}` | Delete or Backspace with statements (else wires) selected |
| `drop` | `{event, position, region}` | a drop carrying one of `dropTypes`, at that page position, inside that region box (innermost; null outside) |
| `edit` | `{id, port, value}` | a literal typed in an input box (`undefined` clears it) |
| `move` | `[{id, position}]` | statements dragged |

While editing, unwired inputs and literal pills carry input boxes and every
merge offers one free control input. A change of the document keeps every
element where it was drawn and routes only the wires whose pins moved
(`layout/place.js`; ELK runs only for an element never drawn before); a new
`relayoutKey`, view or layout option lays out afresh. Exposed methods:
`place(id, position)` (where a statement about to be added is drawn),
`center()` (the page point in the middle of the view), `positions()`,
`relayout()`, `fit(opts)`.

A program's subgraphs drawn as one graph (every `@def` inlined into main) is
KIR's `inline` pass: `run_passes(program, env, ["order_dataflow", "inline"])`,
then `to_graph` as usual.

## Develop

```sh
npm ci
python scripts/generate/examples.py   # dev/examples/: every example graph (needs kohakunode)
npm run dev                         # the gallery at http://127.0.0.1:5199
npm test                            # layout checks over every example, view and variant; editing layouts
npm run build                       # dist/
```

| folder | scripts |
|---|---|
| `scripts/generate/` | `examples.py` (example graphs, with `whole` graphs of programs with `@def`s), `icons.mjs` (the icon bodies in `src/render/icons.js`) |
| `scripts/checks/` | `check.mjs` (layout geometry over every example), `anchors.mjs` (rendered wires end on their pins), `stability.mjs` (a ticking overlay creates or destroys no element) |
| `scripts/inspect/` | `shots.mjs` (screenshots of gallery states), `clip.mjs`, `probe.mjs`, `dataflow.mjs`, `isolate.mjs`, `strategies.mjs` (drawn size under every ELK strategy) |

The rendered scripts (`anchors`, `stability`, `shots`, `clip`, `probe`) drive
the running gallery with `playwright-core` and an installed Chrome or Edge.
