# kir-editor

An example editor for KIR v2. It is a client of the toolchain, not part of
it: the Python package `kohakunode` (in `src/`) parses, checks, converts,
lowers and runs programs; machines consume KIR text.

The editor shows **one program in several visual styles**. The text is the
source of truth; every view is a projection of it, and an edit in any view
rewrites the program, after which every view is drawn again.

| View | Style | Drawn from |
|---|---|---|
| **Nodes** (default) | ComfyUI / Blender / Unreal cards: control runs down, data enters on the left and leaves on the right; literal inputs are input boxes inside the node | the graph document |
| **Flowchart** | classic ROBO Pro: blue program flow from a Start element, orange data lines, yellow VARIABLE elements | the graph document (variables style) |
| **Sequence** | LEGO EV3: a sequence beam of coloured blocks, parameter boxes along their bottoms, data wires underneath | the AST |
| **Blocks** | Scratch: hats, command blocks with slots, C blocks | the AST |
| **Text** | KIR text with highlighting and diagnostics | — |
| **Split** | any two of the above side by side | — |

```
apps/kir-editor/
  backend/                   FastAPI over kohakunode
    kir_editor/
      app.py                 create_app(); `uvicorn kir_editor.app:app`
      config.py              settings from the environment
      api/                   routes and request bodies
      core/
        toolchain.py         every operation as one kohakunode call
        ast_json.py          programs as JSON and back (the statement views' AST)
        demo_nodes.py        `demo`, the runnable node library
    signatures/              .kirsig.json files listed in the palette (`vision`)
    tests/test_api.py        API tests against the golden corpus and the samples
  frontend/                  Vue 3 + Vite + Pinia + UnoCSS + kir-graph + CodeMirror 6
    src/
      api/                   backend client
      stores/
        document/            the program: index (state), sync (text <-> graph / AST), history (undo),
                             edits (graph edits), toolchain (passes, check, lower, run)
        library.js ui.js     node libraries; view knobs
      graph/edit.js          graph edits that keep a .kirgraph valid for from_graph
      program/               statement-view logic: grouping into constructs, edits, new statements
      views/
        nodes/ flowchart/ sequence/ blocks/ text/   one folder per view
        shared/              graph canvas (the editable kir-graph), knob switch, legend
      components/            chrome (header, status bar) and panels (palette, inspector, bottom)
      samples/               programs shipped with the editor
    tests/e2e/               browser smoke test and screenshot tool (playwright-core + Edge)
```

## Run

From the repository root, with `kohakunode` installed in `.venv`:

```bash
uv pip install --python .venv/Scripts/python.exe fastapi uvicorn    # once
cd apps/kir-editor/backend
../../../.venv/Scripts/python.exe -m uvicorn kir_editor.app:app --port 48888
```

In another shell:

```bash
cd apps/kir-editor/frontend
npm install
npm run dev          # http://localhost:5173, proxies /api to 127.0.0.1:48888
```

`KIR_API_TARGET` points the dev proxy at another backend address.
`npm run build` writes a static build to `frontend/dist/`.

The node and flowchart views are the display library
[`packages/kir-graph`](../../packages/kir-graph/README.md), taken from its
source in this repository (`vite.config.js` aliases `@kohaku/kir-graph` to
it and resolves the libraries both share, Vue, Vue Flow and elkjs, from the
editor's own `node_modules`), so the library needs no build or install of
its own here.

Backend settings:

| Variable | Default | Meaning |
|---|---|---|
| `KIR_EDITOR_SIG_DIR` | `backend/signatures` | directories of `.kirsig.json` files (os.pathsep separated); listed in the palette and searched by `@use` |
| `KIR_EDITOR_STEP_BUDGET` | `200000` | node calls one run may make |

## View knobs

Every knob is in the UI and persists per viewer (localStorage). URL
parameters override them for one page load:

| Parameter | Values | Meaning |
|---|---|---|
| `view` | `nodes` `flowchart` `sequence` `blocks` `text` `split` | the view on screen |
| `split` | `<view>,<view>` | the two views of `split` |
| `data` | `variables` (default), `wires` | node view: values inside the graph go through `get` / `set` pills while the graph's inputs and outputs are wired straight to the statements they reach (docs/spec/graph.md), or reads wired straight to their only write |
| `control` | `auto` (default), `exec`, `frames` | node view: Unreal-style exec pins and wires (kir-graph's `nodes` view); or control as boxing (each namespace, branch arm, loop body, `each` body, `@try` / `@except`, `@dataflow` is a framed region, statements top to bottom, no control wires: `frames`); `auto` is frames, or data only (`dataflow`) when the graph has no control statements |
| `lanes` | `stacked` (default), `tabs` | sequence view: switch / parallel / try lanes all shown, or one at a time |
| `sample` | `tour` `factorial` `each` `clamp` | the program to open |
| `graph` | a `@def` name | which graph the node and flowchart views show |
| `theme` | `light` `dark` | |

## Tests

- Backend: `cd apps/kir-editor/backend && ../../../.venv/Scripts/python.exe -m pytest`.
  Against the golden corpus: the graph (both data styles) is the golden
  `.kirgraph` byte for byte; text → graph → text is a fixed point; AST → JSON →
  text is the golden canonical text for every case; plus diagnostics, passes,
  runs of every sample.
- Browser smoke: `cd apps/kir-editor/frontend && npm run test:e2e`. Starts the
  backend and the dev server on their own ports (48931, 5931; `KIR_E2E_API_PORT`,
  `KIR_E2E_WEB_PORT`, `KIR_PYTHON`), drives the installed Microsoft Edge
  headless through playwright-core with a fresh profile, and checks against the
  DOM, the stores (the dev build exposes them as `window.__kir`) and the
  backend's own answers:
  1. node view editing: every node of the graph is drawn; a node dragged in
     from the palette lands where it was dropped and moves no other node; wire
     data and exec; drag a node, after which only it has moved and both its
     wires end on its pins; type a literal in the node's input box, delete,
     undo, redo, undo a typed text change, run, lower with a pass off;
  2. every view (nodes in frames and exec, flowchart, sequence, blocks, text)
     loads the `tour`, `each` and `factorial` samples;
  3. one edit per view round-trips: afterwards `/api/text` of the graph and
     `/api/ast/text` of the AST both equal the text (in frames, also a node
     dropped into a region box, which joins the end of that block);
  4. no page or console errors.
- Screenshots: `npm run shots -- <dir> [filter]` saves one image per view ×
  style (light, plus a dark round).

## Collect loops

The **collect** palette item creates a loop that captures one value at each
normal body end and publishes the ordered result list after completion:

```text
xs = [1, 2]
(xs)collect(item, i, `body`, value -> results)
body:
    (item, 1)add(value)
```

Blocks and Sequence group the body like `each`, but show a **capture at body end**
expression and result-list name. Node/flowchart views use `body` / `done` control
outputs and the returning `next` input. Their `value` data input is marked
`deferred: "body_end"`; it is not read eagerly on entry. The Inspector exposes
that timing and the result target. Both graph data styles and AST editing retain
the capture expression, optional index/discards, and target name.

The Lower panel obtains `expand_collect` from the backend pass catalog. Default
lowering removes `collect`; disabling passes retains authored collect syntax.
The checker reports invalid body/target interactions rather than changing their
meaning during editing. No parallel scheduling is implied by the collection.

## Record signature files

The signature-file loader accepts both `kirsig: 1` and `kirsig: 2`. A format-2
file can declare immutable record schemas alongside ordinary host nodes:

```json
{
  "kirsig": 2,
  "library": "geometry",
  "nodes": [],
  "records": [{
    "name": "Point",
    "fields": [
      {"name": "x", "type": "int"},
      {"name": "y", "type": "int", "default": 0}
    ]
  }]
}
```

Loading it adds `Point.make`, `Point.get.x`, `Point.get.y`, `Point.with.x`, and
`Point.with.y` to the palette, with canonical `geometry.Point` port types.
These schema-derived operations run without host implementation imports;
`with` returns an updated value rather than mutating its input. Ordinary host
nodes in the same file still need implementations to execute.

The browser keeps the original schema declaration in API payloads, not duplicate
generated node entries. Uploaded libraries take precedence over catalog entries
with the same library name. The backend validates field types/defaults, references,
cycles, and generated-name collisions. Text and graph authoring preserve aliases
such as `g.Point` from `@use "geometry" as g`; checking resolves them to the
canonical schema identity without modifying authored text.

## API

Every POST body may carry `signatures` (parsed `.kirsig.json` files the user
loaded) and `use_demo` (default true). User errors are never HTTP errors: they
come back as `diagnostics: [{code, severity, message, line, column}]`.

| Route | Body | Returns |
|---|---|---|
| `POST /api/graph` | `text`, `data` | `graph` (.kirgraph) in that data style, `ast`, `diagnostics` |
| `POST /api/text` | `graph`, `with_meta` | canonical `text`, `ast`, `diagnostics` |
| `POST /api/ast/text` | `ast` | canonical `text`, `diagnostics` |
| `POST /api/check` | `text` | `diagnostics` |
| `POST /api/lower` | `text`, `passes` | `lowered` text, `semantic_hash`, `full_hash`, `diagnostics` |
| `POST /api/run` | `text`, `passes` | `ok`, final `values`, `stdout`, `diagnostics` |
| `GET /api/passes` | | the optimization passes in order, with what each needs |
| `GET /api/signatures` | | `kir.std`, `demo`, then the signature directory |

- `ast`: the program as JSON (`core/ast_json.py`): `{uses, mode, body}`, every
  statement `{type, line, meta?, hint?, …}`, expressions `{name}` / `{lit}`.
- `passes`: pass names in order; omitted or null runs all, `[]` runs the
  program as written.

## How it works

**Text first.** The document store holds the text and its projections: the
graph document (for the node and flowchart views, in the data style they
ask for) and the AST (for the blocks and sequence views). Typing in the text
view re-derives both. A graph edit (adding a node, wiring, deleting, typing in
an input box, the inspector) goes graph → text and re-derives the AST; the
graph stays as the user arranged it, and every element stays where it is
drawn (kir-graph keeps positions across edits of the same graph and lays out
afresh when the graph is re-derived from text). A statement edit in the
blocks or sequence view goes AST → text → graph. Comments live only in the
text: an edit made in another view writes canonical text. Node ids and
positions survive a text edit only when the text carries them (the `@meta`
toggle).

**Undo / redo.** Ctrl+Z, Ctrl+Shift+Z / Ctrl+Y and the header buttons. Every
edit, from any view, first records a snapshot (graph, AST, the matching text)
in a stack of 100; undo and redo swap whole snapshots. Positions are not in
the snapshots: the graph views remember where each node was drawn, so a node
an undo brings back returns to its place. Inside
the text editor and input fields the keys keep their own undo. Opening a file
or sample starts a new history.

**Graph canvas.** The node and flowchart views are one `<KirGraph editable>`
each (`views/shared/GraphCanvas.vue`). The library draws, lays out and routes;
every edit it reports comes back here as an event: a wire drawn between two
pins (vetted by `graph/edit.js` while it is drawn), Delete on the selection, a
drop from the palette (with the region box it landed in), a literal typed in
an input box, a node moved. The document applies it and the library redraws,
keeping every other element in place; wires at a moved element are rerouted
orthogonally. "Lay out again" in the view bar lays the graph out afresh.

**Nodes view.** Cards with a header and one row per port; unwired data inputs
carry an input box: a switch for bool, a number field, a text field, KIR
literal syntax for lists, dicts and None. Variables are pills (`get x` with
its output on the right, `set x` with its input on the left); a literal node
is an amber pill with its own box; a pill serving one port sits beside it.
With `control=exec` control runs down through exec pins; back edges (jumps
back into a loop merge, returns into an `each` node's `next`) are drawn
dashed, and a merge offers a free "+ way in" pin for one more way in. With
`control=frames` each region (kirgraph 3 `regions`) is a box, arms of one
branch / switch / parallel / try side by side, and a node dropped into a
region box joins the end of that region's sequence.

**Flowchart view.** kir-graph's flowchart: commands are rectangles on the
flow, `x = v` is an "= value" pentagon whose output line runs to the VARIABLE
element it writes, branch is a diamond with labelled exits, switch a
hexagon, loops return to a labelled merge, `each` is a loop element with item
and index outputs, parallel a bar, try a red-edged element. A Start element
precedes the first statement and an End element follows every exit; both are
drawn by the view only and never written back.

**Sequence view.** Each script (the program, every `@def`) is a beam of
tiles coloured by library (demo green, kir.std red, other libraries yellow,
`@def` calls turquoise, variable writes magenta with a suitcase). Loops and
`each` are orange containers, branch and switch are switch containers with a
lane per case, parallel and try have a lane per arm. A data wire runs under
the blocks from the plug that last wrote a variable to every parameter box
that reads it, coloured by kind (number yellow, logic green, text orange,
other grey). Click a parameter box to type a literal or a variable name;
drag tiles to reorder or move them between lanes.

**Blocks view.** A hat for the program and a `define` hat per `@def` (its
parameters are reporters). Command blocks have round slots (numbers, text)
and hexagonal ones (conditions); a variable in a slot is an orange reporter.
C blocks: if / else (a `branch` and its two namespaces), switch with a mouth
per case, for-each, loop (`()jump(`L`)` + `L:`, with "repeat loop" for the
jumps back), parallel, try / except, labelled block, @dataflow. Drag blocks
to reorder or nest, click a slot or a name to edit it, drag a variable from
the variables strip into a slot, drop palette entries into any stack.

`program/structure.js` groups a statement with its namespaces only when they
follow it directly, so the grouping is exact: writing the blocks back gives
the statements they came from, and moving a construct keeps where its arms
continue.

**Palette.** Builtins, the program's `@def`s, and every library from
`/api/signatures` plus loaded `.kirsig.json` files. Drag an entry into any
view or click it to add it there. A node from a library the program does not
reach yet adds its `@use`. `demo` is given to every program unaliased while
"in scope without @use" is on; turn it off when a loaded library shares node
names with it (they would be ambiguous, E011).

**Free nodes.** A call or assign node with no control edge belongs to the
dataflow part of the graph: graph → text puts all such nodes in one
`@dataflow:` block at the top (graph.md). Wire it into the control chain (or,
in frames style, drop it into a region) when it reads something the chain
writes.

**Run.** `demo` (backend `core/demo_nodes.py`) has implementations; other
libraries are signatures only, so a program using them checks, converts and
lowers but fails at run time with "no implementation".
